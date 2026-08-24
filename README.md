# 🐕 Hound

**Hound watches the third-party APIs your code depends on, and tells you exactly when — and where — a change will break you.**

[![CI](https://img.shields.io/github/actions/workflow/status/your-org/hound/ci.yml?branch=main)](https://github.com/your-org/hound/actions)
[![PyPI](https://img.shields.io/pypi/v/hound-watchdog)](https://pypi.org/project/hound-watchdog/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)

Most API changelogs are noise. A vendor renames a field, deprecates a param, or tightens a rate limit — and you find out in production, three weeks later, from a stack trace.

Hound doesn't just diff the spec. It **cross-references every change against how your codebase actually calls that API**, so you only get paged when something you use is actually affected — with the exact file and line to fix.

```
$ hound check

🐕 Hound found 1 breaking change

  stripe · /v1/charges
  ⚠ BREAKING: field `source` is being removed (deprecated since 2026-05-01)
  → used in src/services/payments/charge.py:42

  1 non-breaking change suppressed (run with --verbose to see all)
```

---

## Table of contents

- [Why Hound](#why-hound)
- [How it works](#how-it-works)
- [Install](#install)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [GitHub Action](#github-action)
- [CLI reference](#cli-reference)
- [Severity model](#severity-model)
- [Supported languages & API types](#supported-languages--api-types)
- [Architecture](#architecture)
- [Comparison with other tools](#comparison-with-other-tools)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)

---

## Why Hound

Every team that integrates a third-party API eventually gets burned by a silent change. The existing options are unsatisfying:

- **Do nothing** — find out in production.
- **Watch the changelog manually** — doesn't scale past 2–3 dependencies, and most changes don't matter to *your* usage.
- **Generic OpenAPI diff tools** — tell you the spec changed, not whether your code is affected. Every run is noisy, so teams mute the alerts within a month.

Hound's premise: **a change only matters if your code touches it.** So it builds a map of what your codebase actually reads and writes on each API, and only raises an alert when a real change intersects that map.

## How it works

```
┌─────────────────┐     ┌──────────────────┐     ┌───────────────────┐
│  Spec Fetcher    │────▶│   Diff Engine     │────▶│                   │
│ (OpenAPI/Swagger)│     │ (structural +     │     │                   │
└─────────────────┘     │  semantic)        │     │    Correlator     │────▶ Report
┌─────────────────┐     └──────────────────┘     │ (blast-radius      │    (GitHub Issue /
│  Usage Scanner   │────────────────────────────▶│  matching)         │     Slack / JSON)
│ (AST over your   │                              │                   │
│  codebase)        │                              └───────────────────┘
└─────────────────┘
```

1. **Fetch** — pulls the current OpenAPI/Swagger spec (or scrapes changelog pages when no spec exists) and compares it against the last known-good snapshot stored in `.hound/snapshots/`.
2. **Diff** — computes a structural diff (added/removed/renamed fields, changed required-ness, new deprecations, type changes) plus a semantic diff for prose-only changes (deprecation notices, rate-limit language) using sentence-embedding similarity.
3. **Scan** — walks your codebase with AST parsing to build a usage table: every endpoint, field, and parameter your code actually touches, with file and line number.
4. **Correlate** — intersects the diff against the usage table. Only intersecting changes are surfaced as actionable; everything else is available in verbose output but doesn't trigger a notification.
5. **Report** — opens a GitHub Issue (or posts to Slack) with the exact change, severity, and the file:line that needs attention.

## Install

```bash
pip install hound-watchdog
```

Or run without installing, via `uvx`:

```bash
uvx hound-watchdog check
```

Requires Python 3.10+.

## Quick start

```bash
# 1. Initialize config in your repo
hound init

# 2. Add an API to watch
hound add stripe \
  --spec-url https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.json \
  --scan-path src/services/payments/

# 3. Run a check
hound check

# 4. (optional) Set up scheduled watching via GitHub Actions
hound init --with-action
```

The first run establishes a baseline snapshot — no alerts fire. Every subsequent run diffs against that baseline and advances it once the diff is reported.

## Configuration

`hound.yaml`, created by `hound init`:

```yaml
version: 1

watch:
  - name: stripe
    spec_url: https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.json
    scan_paths:
      - src/services/payments/
    language: python

  - name: github-api
    spec_url: https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.json
    scan_paths:
      - src/integrations/github/
    language: python
    ignore_fields:
      - "*.deprecated_beta_field"   # explicitly acknowledged, don't re-alert

report:
  github_issues:
    enabled: true
    labels: ["hound", "dependency-risk"]
    assignees: []
  slack:
    enabled: false
    webhook_url: ${SLACK_WEBHOOK_URL}
  min_severity: breaking   # breaking | deprecation | non_breaking

llm:
  provider: openai          # openai | azure_openai | huggingface_local | none
  model: gpt-4o-mini
  api_key: ${OPENAI_API_KEY}
  # provider: none  -> disables prose summarization; structural diffs only
```

Config is validated against a versioned JSON schema on every run (`hound validate`), so a bad config fails fast in CI rather than silently skipping a watch target.

## GitHub Action

Zero-infrastructure scheduled watching:

```yaml
# .github/workflows/hound.yml
name: Hound API Watch
on:
  schedule:
    - cron: '0 9 * * 1'   # every Monday, 9am UTC
  workflow_dispatch: {}

jobs:
  watch:
    runs-on: ubuntu-latest
    permissions:
      issues: write
    steps:
      - uses: actions/checkout@v4
      - uses: your-org/hound-action@v1
        with:
          config: hound.yaml
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
```

## CLI reference

| Command | Description |
|---|---|
| `hound init` | Scaffold `hound.yaml` in the current repo |
| `hound add <name> --spec-url <url> --scan-path <path>` | Register a new API to watch |
| `hound check` | Run a full check: fetch, diff, scan, correlate, report |
| `hound check --dry-run` | Run without writing reports or advancing the snapshot |
| `hound check --verbose` | Show all changes, including non-breaking / unaffected ones |
| `hound validate` | Validate `hound.yaml` against the config schema |
| `hound baseline reset <name>` | Discard stored snapshot and re-baseline on next check |
| `hound diff <name>` | Show the raw structural diff without running the correlator |

Exit codes: `0` no breaking changes, `1` breaking change found, `2` config or fetch error — designed to gate CI pipelines.

## Severity model

| Severity | Meaning | Default action |
|---|---|---|
| `breaking` | A field/endpoint your code uses was removed, renamed, or made incompatible | Issue opened, CI can be gated to fail |
| `deprecation` | A field/endpoint your code uses is marked deprecated but still functional | Issue opened, non-blocking |
| `non_breaking` | Spec changed but doesn't intersect your usage table | Logged only, suppressed from notifications by default |

Severity classification for structural changes is deterministic (rule-based on the OpenAPI diff). Severity for prose-only changes (rate limits, policy notices) is LLM-assisted and always shown with the source excerpt it was derived from, so you can verify the classification rather than trust it blindly.

## Supported languages & API types

**v1 (current):**
- Spec format: OpenAPI 3.x / Swagger 2.0
- Codebase scanning: Python (`requests`, `httpx`, and popular SDK call patterns)

**Planned (see [Roadmap](#roadmap)):** TypeScript/JavaScript scanning, GraphQL schema diffing, docs-only (non-spec) API tracking via semantic diff.

If your API has no published spec, or your language isn't supported yet, Hound will tell you explicitly rather than silently skipping — check `hound check --verbose` output for `unsupported_target` warnings.

## Architecture

```
hound/
├── hound/
│   ├── fetchers/
│   │   ├── openapi_fetcher.py     # spec retrieval + parsing
│   │   └── docs_fetcher.py        # fallback for non-spec APIs
│   ├── diffing/
│   │   ├── spec_diff.py           # structural diff
│   │   └── semantic_diff.py       # embedding-based diff for prose
│   ├── usage_scanner/
│   │   ├── ast_scanner.py         # AST walk for API call sites
│   │   └── field_extractor.py     # endpoint/field usage table
│   ├── correlator.py              # blast-radius matching
│   ├── reporter/
│   │   ├── github_issue.py
│   │   └── slack_notify.py
│   ├── store/
│   │   └── snapshot_store.py      # baseline persistence
│   └── agent.py                   # orchestration (fetch → diff → scan → correlate → report)
├── cli.py
├── configs/schema.json            # versioned config schema
└── tests/
```

**Design principles:**
- **Deterministic core, LLM-assisted edges.** Structural diffing and correlation never depend on an LLM call — they work with `llm.provider: none`. The LLM only summarizes prose changes and drafts human-readable issue text.
- **Idempotent runs.** Re-running `hound check` without a new spec change produces no duplicate issues; snapshot state is only advanced after a successful report.
- **Fails loud, not silent.** Fetch failures, schema-validation failures, and unsupported targets all surface as explicit warnings/errors, never a quiet no-op.
- **No required external infra.** Local snapshot storage by default (`.hound/`); S3/GCS backend is optional for teams running Hound centrally across many repos.

## Comparison with other tools

| | Hound | Generic OpenAPI diff | Dependabot/Renovate |
|---|---|---|---|
| Detects spec changes | ✅ | ✅ | ❌ (version bumps only) |
| Tells you *your* blast radius | ✅ | ❌ | ❌ |
| File:line of affected code | ✅ | ❌ | ❌ |
| Works with no spec (docs-only APIs) | 🔜 planned | ❌ | ❌ |
| Noise level | Low (usage-filtered) | High (alerts on every change) | N/A |

## Roadmap

- [ ] TypeScript/JavaScript AST scanning
- [ ] GraphQL schema diffing
- [ ] Docs-only API tracking (semantic diff without a formal spec)
- [ ] Hosted mode (multi-repo dashboard, no self-managed cron)
- [ ] VS Code extension surfacing warnings inline at the call site

## Contributing

Issues and PRs welcome. Before opening a PR:

```bash
git clone https://github.com/your-org/hound
cd hound
pip install -e ".[dev]"
pytest
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for coding standards and how to add support for a new language scanner.

## Security

Hound only reads public spec URLs and your local codebase — it never transmits your source code to an LLM provider; only extracted, minimal context (field names, endpoint paths) is sent when `llm.provider` is set to a hosted model. Set `llm.provider: none` or use `huggingface_local` for a fully offline run. Report vulnerabilities via [SECURITY.md](SECURITY.md), not public issues.

## License

MIT — see [LICENSE](LICENSE).