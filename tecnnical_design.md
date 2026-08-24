# Hound — Technical Design

This document specifies the core logic, workflow, and technology choices for Hound. It exists to answer one question honestly: *what exactly does Hound compute, in what order, and why is each piece built the way it is.*

---

## 1. Build-vs-buy decision (read this first)

Before designing Hound's internals, it's worth being honest about what already exists, so effort goes where it's actually differentiated.

| Problem | Existing OSS solution | Verdict |
|---|---|---|
| Structural OpenAPI diffing (added/removed fields, breaking-change classification) | **oasdiff** — mature, Go-based, 500+ breaking-change rules, CLI + GitHub Action | **Use it.** Shell out to it or call it via its Go library / generated JSON output. Do not reimplement. |
| Spec fetching/parsing | `openapi-spec-validator`, `prance` (Python) | Use existing libraries. |
| Semantic diff of prose docs | No mature OSS tool for this specific case | **Build it.** Genuine gap. |
| Mapping API usage to your own codebase, and correlating that against a diff | No existing tool does this | **Build it — this is Hound's actual product.** |

This reframes Hound's scope precisely: **Hound is not an OpenAPI diff tool. It's a correlation engine that sits on top of a diff tool (oasdiff) and your codebase.** That's a smaller, sharper build, and it's the part nobody else has shipped.

---

## 2. Core logic, precisely stated

For a given `(api, codebase)` pair:

1. Obtain `spec_old` (last known-good snapshot) and `spec_new` (freshly fetched).
2. `raw_diff = oasdiff.breaking(spec_old, spec_new)` — a structured list of changes, each with an OpenAPI path, an operation, and a breaking/non-breaking classification.
3. Independently, build `usage_table = scan(codebase)` — every `(endpoint, field, file, line)` tuple the code actually touches, derived from static analysis, not from the spec.
4. `relevant_changes = correlate(raw_diff, usage_table)` — the set intersection, by endpoint+field, between what changed and what's used.
5. For changes in `relevant_changes` that are structural (covered by oasdiff's rules), severity is deterministic — inherited directly from oasdiff's classification.
6. For changes that are prose-only (rate-limit language, policy notices with no spec representation), run `semantic_diff` and an LLM classification pass, always attaching the source excerpt for human verification.
7. Emit a report: only `relevant_changes`, each with severity, the affected endpoint/field, and the exact `file:line` from the usage table.
8. Advance the stored snapshot to `spec_new` **only after** the report is successfully delivered (idempotency — see §7).

Everything else in this document is implementation detail around these eight steps.

---

## 3. Full workflow (sequence)

```
┌──────────┐     ┌───────────────┐     ┌─────────────┐     ┌────────────┐     ┌───────────┐
│ Trigger  │────▶│ Fetch spec_new │────▶│ oasdiff vs   │────▶│ Usage scan  │────▶│ Correlate │
│ (cron/   │     │ + validate     │     │ spec_old     │     │ of codebase │     │           │
│ manual)  │     └───────────────┘     └─────────────┘     └────────────┘     └───────────┘
└──────────┘                                                                          │
                                                                                        ▼
                    ┌────────────────┐     ┌───────────────┐     ┌──────────────────────┐
                    │ Advance         │◀────│ Report (Issue/ │◀────│ Severity classify     │
                    │ snapshot        │     │ Slack/JSON)    │     │ (deterministic +      │
                    │ (on success)    │     │                │     │ LLM for prose-only)   │
                    └────────────────┘     └───────────────┘     └──────────────────────┘
```

**Trigger sources:** GitHub Actions cron, manual CLI invocation, or (future hosted mode) a webhook from a spec registry.

**Failure semantics at each stage:**
- Fetch fails → error, exit code 2, snapshot untouched, no report generated (never silently skip).
- oasdiff fails to parse a spec → error, surfaced explicitly, not swallowed.
- Usage scan finds zero call sites for a watched path → warning, not silence — likely a misconfigured `scan_paths`.
- Report delivery fails (e.g., GitHub API rate limit) → retry with backoff; snapshot is **not** advanced until delivery succeeds, so the next run naturally retries the same diff.

---

## 4. Component design

### 4.1 Spec Fetcher (`fetchers/openapi_fetcher.py`)
- Pulls the spec from a URL or local path.
- Normalizes via `prance` (resolves `$ref`s) so downstream diffing sees a fully-resolved document.
- Computes a content hash; if unchanged since last run, short-circuits the entire pipeline (no diff, no scan, no LLM call — cheap no-op).

### 4.2 Diff Engine (`diffing/spec_diff.py`)
- Wraps `oasdiff` as a subprocess (`oasdiff breaking --format json`) rather than reimplementing OpenAPI semantics. This is the single most important architectural decision in this doc — see §1.
- Parses oasdiff's JSON output into Hound's internal `ChangeRecord` model:
  ```python
  @dataclass
  class ChangeRecord:
      endpoint: str  # e.g. "/v1/charges"
      method: str  # e.g. "POST"
      field: str | None  # e.g. "source"
      change_type: str  # "field_removed" | "field_added" | "required_added" | ...
      breaking: bool  # from oasdiff's classification
      raw: dict  # original oasdiff entry, kept for audit
  ```
- If a target API has no OpenAPI spec at all, this component is skipped and `docs_fetcher.py` + `semantic_diff.py` handle it instead (see §4.5).

### 4.3 Usage Scanner (`usage_scanner/ast_scanner.py`) — **the core original component**
This is where Hound's actual engineering effort belongs. Two viable strategies, in order of preference:

**Strategy A — AST-based static analysis (default, v1).**
- Python: use the standard `ast` module to walk the syntax tree, pattern-matching against known call shapes:
  - Direct HTTP calls: `requests.get("https://api.stripe.com/v1/charges", ...)`, `httpx.post(...)`
  - SDK calls: `stripe.Charge.create(...)` — matched via a small, extensible per-SDK mapping table (`sdk_signatures.yaml`) rather than hardcoded, so community contributions can add new SDKs without touching core code.
- For each match, extract: endpoint path (resolve string concatenation/f-strings where feasible, flag as `dynamic_unresolved` otherwise), HTTP method, and which response fields are accessed downstream (via simple dataflow: track the variable the response is assigned to, look for `.attribute` or `["key"]` accesses on it within the same function scope).
- Multi-language support (TS/JS, later) uses `tree-sitter` instead of language-native ASTs, since tree-sitter grammars exist for every mainstream language and keep the scanner architecture uniform.

**Strategy B — agentic investigation (future, for cases Strategy A can't resolve statically).**
CodeRabbit's approach is instructive here: rather than giving the model a fixed set of tool schemas, their review agent investigates a codebase by writing shell commands (`grep`, `cat`, `ast-grep`) inside a sandbox and reading the output, which sidesteps the maintenance burden of a large structured tool-call surface and generalizes better to code patterns nobody anticipated. Hound can adopt the same pattern for cases where static AST matching is ambiguous (e.g., dynamically constructed URLs, indirect SDK wrapper functions): drop into a sandboxed shell, let an agent run `ast-grep`/`grep` to locate real call sites, and treat its findings as lower-confidence usage entries requiring human confirmation in the report. This is explicitly a v2 feature — v1 ships with Strategy A only, which covers the large majority of real-world call patterns and has zero LLM cost or latency.

Output: a `usage_table.json`, structurally:
```json
{
  "stripe": [
    {"endpoint": "/v1/charges", "method": "POST", "fields_read": ["source", "amount"], "fields_written": ["amount", "currency"], "file": "src/services/payments/charge.py", "line": 42}
  ]
}
```

### 4.4 Correlator (`correlator.py`)
Pure function, no I/O, fully unit-testable:
```python
def correlate(changes: list[ChangeRecord], usage: list[UsageRecord]) -> list[Finding]:
    findings = []
    for change in changes:
        matches = [
            u
            for u in usage
            if u.endpoint == change.endpoint
            and (change.field is None or change.field in u.fields_read + u.fields_written)
        ]
        if matches:
            findings.append(Finding(change=change, usage_sites=matches, severity=classify(change)))
    return findings
```
The correlator is deliberately the simplest component in the system — it's a join, not a model. Complexity belongs in the scanner (getting the usage table right) and the diff engine (getting the change classification right), not here. Keeping the correlation logic dumb and deterministic is what makes the tool trustworthy — a false negative here (a missed correlation) is a silent production incident, so this path has the highest test-coverage bar in the codebase.

### 4.5 Semantic Diff, for docs without a spec (`diffing/semantic_diff.py`)
- Chunk old and new doc pages (by heading section).
- Embed both sets with a local sentence-transformer model (e.g., `all-MiniLM-L6-v2` via HuggingFace, runs on CPU, no external API call needed for this step).
- Pair chunks by nearest-neighbor cosine similarity; pairs below a similarity threshold are flagged as "meaningfully changed."
- Only flagged chunks proceed to LLM classification — this keeps LLM usage proportional to actual change volume, not full-document re-processing every run.

### 4.6 Severity Classifier (`correlator.py` + `llm/classify.py`)
- Structural changes: severity is inherited directly from oasdiff (`breaking: true/false`), no LLM involved — deterministic and free.
- Prose-only changes: an LLM call classifies into `breaking | deprecation | non_breaking`, with the prompt constrained to output structured JSON only, and the source excerpt always attached to the output so a human can verify the classification rather than trust it blindly. This mirrors CodeRabbit's context-engineering principle: the model is given tightly scoped, relevant context (the specific changed excerpt) rather than the entire changelog, since more context isn't automatically better context — it's easy for signal to drown if the model is handed too much at once.

### 4.7 Reporter (`reporter/github_issue.py`, `reporter/slack_notify.py`)
- Idempotent by design: before creating an issue, search for an open issue with a matching content-hash label; update instead of duplicate.
- Issue template includes: the change, the affected `file:line`(s), severity, and — for LLM-classified findings only — the source excerpt the classification was derived from.

### 4.8 Snapshot Store (`store/snapshot_store.py`)
- v1: local JSON file at `.hound/snapshots/<api-name>.json`, committed to the repo (so CI runners have consistent state without needing external storage).
- Pluggable backend interface (`SnapshotStore` ABC) so a future hosted mode can swap in S3/GCS/Postgres without touching the pipeline logic.

---

## 5. Tech stack, with rationale

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.10+ | Matches your existing stack, best library support for both AST tooling and the LLM ecosystem (LangChain, HF, OpenAI SDK) |
| Structural OpenAPI diff | **oasdiff** (external binary/subprocess) | Mature, correct, actively maintained — see §1 |
| Codebase static analysis | Python `ast` (v1), `tree-sitter` (multi-language, v2) | Zero-dependency for the primary language; tree-sitter avoids maintaining N language-specific parsers |
| Embeddings (semantic diff) | HuggingFace `sentence-transformers`, local | No API cost, no external dependency for the deterministic-ish core capability; keeps `llm.provider: none` truly functional |
| Vector storage for doc chunks | Chroma (local, embedded) | No external service required for a CLI-first OSS tool; users who want to self-host at scale can swap for Qdrant via the same interface |
| LLM (optional layer) | Pluggable: OpenAI / Azure OpenAI / local HF model | Never a hard dependency — v1's structural path works with zero LLM calls |
| Orchestration | Plain Python pipeline + LangGraph only where genuinely stateful (the fetch→diff→scan→correlate→report chain is linear enough not to need a graph framework for v1) | Avoid over-engineering; add LangGraph when retry/branching logic actually gets complex enough to need it (e.g., v2 agentic scanning) |
| CLI | `click` or `typer` | Standard, well-documented, good help-text ergonomics |
| Scheduling (v1) | GitHub Actions cron | Zero infrastructure for the OSS user — this matters more than any framework choice for adoption |
| Scheduling (hosted, future) | Cloud Run / Cloud Tasks queue pattern (as CodeRabbit uses) — a webhook or cron trigger drops jobs onto a queue, workers pull and process independently | This absorbs bursty load (many repos checking in at once) without a rearchitecture; worth adopting the pattern early even before hosted mode ships, since it's cheap to design for now and expensive to retrofit later |
| Sandbox for agentic scanning (v2 only) | Ephemeral container (Docker) or microVM, matching CodeRabbit's isolation model | Only needed once Strategy B (agentic shell-command investigation) is introduced — v1's static AST scanner needs no sandbox since it never executes untrusted code, only parses it |

**A note on why v1 deliberately avoids the heaviest infrastructure:** CodeRabbit's production system runs full builds inside isolated microVMs with 20+ linters, because it needs to *execute and understand* arbitrary untrusted repositories at review time. Hound's job is narrower — parse (not execute) a known repository the user has already granted access to, and diff two spec documents. That narrower job doesn't need sandboxed execution in v1, and adding it prematurely would slow down shipping the part that's actually differentiated (the correlator). Sandbox architecture is deferred to v2's agentic scanning strategy, where it becomes genuinely necessary.

---

## 6. Data flow summary

```
spec_old.json (snapshot) ─┐
                            ├─▶ oasdiff ─▶ ChangeRecord[] ─┐
spec_new.json (fetched)  ─┘                                 ├─▶ Finding[] ─▶ Reporter ─▶ GitHub Issue / Slack
codebase/ ─▶ ast_scanner ─▶ UsageRecord[] ────────────────┘
```

Everything left of `Finding[]` is deterministic and independently unit-testable with fixture files (a pair of spec versions + a small sample codebase). This is intentional: the test suite should be able to verify "given this spec diff and this codebase, exactly these findings are produced" without ever calling an LLM or hitting the network.

---

## 7. Idempotency & reliability guarantees

These are the properties that separate a production-grade tool from a script that happens to work in a demo:

1. **No duplicate reports.** Content-hash-tagged issues; re-running against an unchanged spec produces zero API calls beyond the initial fetch (short-circuited at §4.1).
2. **No lost changes.** Snapshot only advances after successful report delivery — a crashed run naturally retries the same diff on the next invocation rather than silently skipping it.
3. **No silent scope gaps.** Unsupported languages, unresolvable dynamic endpoints, and fetch failures all produce explicit warnings/errors in output, never a quiet no-op that looks like "everything's fine."
4. **Deterministic core.** The fetch→diff→scan→correlate path never depends on model output. Only prose-only severity classification touches an LLM, and even that always ships with the source excerpt so a human can audit the classification.
5. **Config schema versioning.** `hound.yaml` is validated against a versioned JSON schema (`configs/schema.json`) on every run — a malformed config fails loudly in CI, not silently at 3am when a scheduled run does nothing.

---

## 8. Testing strategy

| Layer | Test approach |
|---|---|
| `spec_diff.py` | Fixture pairs of real spec versions (e.g., two historical Stripe spec snapshots) with hand-verified expected `ChangeRecord` output |
| `ast_scanner.py` | A small fixture codebase with known call sites; assert the exact `usage_table` produced |
| `correlator.py` | Pure unit tests — synthetic `ChangeRecord`/`UsageRecord` inputs, no fixtures needed, this is the highest-coverage-bar component |
| `semantic_diff.py` | Fixture doc-chunk pairs with known "changed" vs "unchanged" labels, threshold-tuned against these |
| End-to-end | One real worked example per supported API (Stripe, GitHub) run against a small demo repo, checked into `examples/`, run in CI to catch regressions against real-world specs |

---

## 9. What "v1 done" looks like

- OpenAPI-spec APIs only (no docs-only fallback yet)
- Python codebases only
- `oasdiff` as the diff engine, wrapped and parsed
- Static AST usage scanning, no agentic/sandbox component
- GitHub Issues as the only reporter
- `llm.provider: none` works end-to-end with zero degradation of the core correlation feature
- One real example repo in `examples/` that a stranger can clone and see a real finding fire

Everything past this line (TS/JS scanning, agentic Strategy B, hosted mode, Slack reporting) is explicitly v2+ and documented in the README roadmap, not built now.