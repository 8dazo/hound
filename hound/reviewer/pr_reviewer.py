"""CodeRabbit-style PR Reviewer for API dependencies and blast radius."""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Set

import requests

from hound.correlator import correlate
from hound.diffing.spec_diff import SpecDiffEngine
from hound.fetchers.openapi_fetcher import OpenAPIFetcher
from hound.models import ChangeRecord, Finding, HoundConfig, UsageRecord, WatchTargetConfig
from hound.store.snapshot_store import LocalSnapshotStore
from hound.usage_scanner.ast_scanner import ASTScanner
from hound.usage_scanner.ts_scanner import TSScanner

logger = logging.getLogger(__name__)


@dataclass
class InlineComment:
    path: str
    line: int
    body: str


@dataclass
class PRReviewResult:
    verdict: str  # "APPROVE" | "COMMENT" | "REQUEST_CHANGES"
    summary: str
    inline_comments: List[InlineComment] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)


class PRReviewer:
    """Reviews Git pull request diffs for third-party API dependencies and breaking changes."""

    def __init__(self, config: HoundConfig) -> None:
        self.config = config
        self.py_scanner = ASTScanner()
        self.ts_scanner = TSScanner()
        self.store = LocalSnapshotStore()
        self.diff_engine = SpecDiffEngine()
        self.fetcher = OpenAPIFetcher()

    def get_git_diff_changed_lines(self, base_ref: str = "origin/main") -> Dict[str, Set[int]]:
        """Extract changed line numbers per file using git diff."""
        try:
            cmd = ["git", "diff", "-U0", f"{base_ref}...HEAD"]
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode != 0:
                # Fallback to single commit diff
                cmd = ["git", "diff", "-U0", "HEAD~1...HEAD"]
                res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            return self.parse_diff_lines(res.stdout)
        except Exception as e:
            logger.warning(f"Failed to get git diff: {e}")
            return {}

    def parse_diff_lines(self, diff_text: str) -> Dict[str, Set[int]]:
        """Parse unified diff output to extract added/modified line numbers."""
        changed: Dict[str, Set[int]] = {}
        current_file: str | None = None

        for line in diff_text.splitlines():
            if line.startswith("+++ b/"):
                current_file = line[6:].strip()
                if current_file not in changed:
                    changed[current_file] = set()
            elif line.startswith("@@ ") and current_file:
                # @@ -old,count +new,count @@
                m = re.search(r"\+(\d+)(?:,(\d+))?", line)
                if m:
                    start_line = int(m.group(1))
                    count = int(m.group(2)) if m.group(2) is not None else 1
                    for l_no in range(start_line, start_line + max(1, count)):
                        changed[current_file].add(l_no)

        return changed

    def review_diff(self, changed_lines_map: Dict[str, Set[int]]) -> PRReviewResult:
        """Scan only changed files and lines against current API specifications."""
        all_findings: List[Finding] = []
        all_usages: List[UsageRecord] = []
        inline_comments: List[InlineComment] = []

        for target in self.config.watch:
            findings, usages = self._review_target(target, changed_lines_map)
            all_findings.extend(findings)
            all_usages.extend(usages)

        breaking_count = sum(1 for f in all_findings if f.is_breaking)
        dep_count = sum(1 for f in all_findings if f.severity == "deprecation")

        # Generate inline comments
        for finding in all_findings:
            sev_emoji = (
                "🔴 **BREAKING API CHANGE**" if finding.is_breaking else "⚠️ **DEPRECATION NOTICE**"
            )
            for site in finding.usage_sites:
                body = (
                    f"🐕 **Hound API Review** · {sev_emoji}\n\n"
                    f"**Endpoint**: `{finding.change.method} {finding.change.endpoint}`\n"
                    f"**Issue**: {finding.change.description}\n\n"
                    f"> {finding.reason}\n\n"
                    f"💡 *Suggestion*: Verify whether an updated field or endpoint should be used before merging."
                )
                inline_comments.append(InlineComment(path=site.file, line=site.line, body=body))

        # Generate executive summary with optional AI insights
        summary = self._generate_summary(all_findings, all_usages, breaking_count, dep_count)
        verdict = (
            "REQUEST_CHANGES" if breaking_count > 0 else ("COMMENT" if dep_count > 0 else "APPROVE")
        )

        return PRReviewResult(
            verdict=verdict,
            summary=summary,
            inline_comments=inline_comments,
            findings=all_findings,
        )

    def _review_target(
        self, target: WatchTargetConfig, changed_lines_map: Dict[str, Set[int]]
    ) -> tuple[List[Finding], List[UsageRecord]]:
        """Review changed lines for a single watch target."""
        # 1. Fetch current spec or load cached snapshot
        current_spec = None
        if target.spec_url:
            try:
                fetch_res = self.fetcher.fetch(target.spec_url)
                current_spec = fetch_res.spec
            except Exception:
                pass

        if not current_spec:
            current_spec = self.store.get_snapshot(target.name)

        if not current_spec:
            return [], []

        # 2. Extract baseline spec diff (if available) + any active deprecations in current spec
        diff_changes = []
        old_snap = self.store.get_snapshot(target.name)
        if old_snap:
            diff_changes = self.diff_engine.diff(old_snap, current_spec)
        else:
            diff_changes = self._extract_active_deprecations(current_spec)

        # 3. Scan only changed files
        usages: List[UsageRecord] = []
        for file_path_str, lines in changed_lines_map.items():
            fpath = Path(file_path_str)
            if not fpath.is_file():
                continue

            if fpath.suffix == ".py":
                records = self.py_scanner.scan_file(fpath)
            elif fpath.suffix in {".ts", ".tsx", ".js", ".jsx"}:
                records = self.ts_scanner.scan_file(fpath)
            else:
                continue

            # Filter usage records on changed lines
            for r in records:
                if not lines or r.line in lines:
                    usages.append(r)

        if not usages or not diff_changes:
            return [], usages

        findings = correlate(
            changes=diff_changes,
            usage=usages,
            min_severity="deprecation",
            ignore_fields=target.ignore_fields,
        )
        return findings, usages

    def _extract_active_deprecations(self, spec: Dict[str, Any]) -> List[ChangeRecord]:
        """Scan active specification to detect any currently deprecated operations and fields."""
        changes: List[ChangeRecord] = []
        paths = spec.get("paths") or {}
        http_methods = {"get", "post", "put", "delete", "patch", "options", "head"}

        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            path_dep = bool(path_item.get("deprecated"))

            for method in http_methods:
                if method not in path_item:
                    continue
                op = path_item[method]
                if not isinstance(op, dict):
                    continue

                if path_dep or op.get("deprecated"):
                    changes.append(
                        ChangeRecord(
                            endpoint=path,
                            method=method.upper(),
                            change_type="operation_deprecated",
                            breaking=False,
                            description=f"Endpoint `{method.upper()} {path}` is marked as deprecated in API specification",
                            raw=op,
                        )
                    )

                # Check parameters
                for p in op.get("parameters", []):
                    if isinstance(p, dict) and p.get("deprecated"):
                        p_name = p.get("name")
                        changes.append(
                            ChangeRecord(
                                endpoint=path,
                                method=method.upper(),
                                field=p_name,
                                change_type="parameter_deprecated",
                                breaking=False,
                                description=f"Parameter `{p_name}` on `{method.upper()} {path}` is marked as deprecated",
                                raw=p,
                            )
                        )

        return changes

    def _generate_ai_insight(
        self, findings: List[Finding], verified_sites: List[UsageRecord]
    ) -> str | None:
        """Generate OpenRouter-powered AI insights for the PR review."""
        import os

        api_key = self.config.llm.api_key or os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            return None

        model = self.config.llm.model or "stealth/ox-alpha"
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/8dazo/hound",
            "X-Title": "Hound API Watchdog",
        }

        sites_desc = (
            "\n".join(
                f"- `{s.method} {s.endpoint}` in `{s.file}:{s.line}`" for s in verified_sites[:10]
            )
            or "None detected"
        )
        findings_desc = (
            "\n".join(
                f"- `{f.change.method} {f.change.endpoint}`: {f.reason}" for f in findings[:10]
            )
            or "None (Clean integration)"
        )

        prompt = f"""You are Hound AI, an automated API watchdog reviewer.
The pull request contains the following API call sites and compatibility findings:

Verified API Call Sites:
{sites_desc}

Compatibility Findings:
{findings_desc}

Provide a concise, 2-3 sentence technical review commentary and recommendations for the engineering team. Do not use generic filler words."""

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are Hound AI, a CodeRabbit-style API compatibility review bot.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=15.0)
            if resp.status_code == 200:
                content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                if content:
                    return f"\n### 🤖 AI Review Summary (`{model}`)\n\n{content.strip()}\n"
        except Exception as e:
            logger.warning(f"OpenRouter AI summary request failed: {e}")

        return None

    def _generate_summary(
        self,
        findings: List[Finding],
        usages: List[UsageRecord],
        breaking_count: int,
        dep_count: int,
    ) -> str:
        """Format CodeRabbit-style markdown executive summary for the PR."""
        ai_insight = self._generate_ai_insight(findings, usages) or ""

        if not findings:
            verified_section = ""
            if usages:
                verified_lines = ["\n### 🔍 Verified Endpoints:"]
                for u in usages:
                    verified_lines.append(f"- `{u.method} {u.endpoint}` (`{u.file}:{u.line}`)")
                verified_section = "\n".join(verified_lines) + "\n"

            return (
                "## 🐕 Hound API Review\n\n"
                "✅ **All third-party API dependencies verified!**\n\n"
                "No breaking API changes or deprecated field usages were detected in this pull request.\n\n"
                "| API Target | Status | Usage Sites |\n"
                "| :--- | :--- | :--- |\n"
                f"| `{len(self.config.watch)} target(s)` | ✅ Clean | {len(usages)} active call site(s) |\n"
                f"{verified_section}"
                f"{ai_insight}"
                "\n---\n"
                "*Generated automatically by [Hound API Watchdog](https://github.com/8dazo/hound)*"
            )

        status_emoji = "🚨 **Changes Requested**" if breaking_count > 0 else "⚠️ **Review Warnings**"
        lines = [
            f"## 🐕 Hound API Review · {status_emoji}\n",
            f"Hound analyzed the third-party API dependencies in this pull request and found **{len(findings)} relevant item(s)**:\n",
            f"- 🔴 **Breaking Changes**: {breaking_count}",
            f"- ⚠️ **Deprecation Notices**: {dep_count}\n",
            "### 💥 Blast Radius Impact Table\n",
            "| Severity | Method | Endpoint | Field | File Location |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]

        for f in findings:
            sev_badge = "🔴 `BREAKING`" if f.is_breaking else "🟡 `DEPRECATED`"
            for site in f.usage_sites:
                lines.append(
                    f"| {sev_badge} | `{f.change.method}` | `{f.change.endpoint}` | `{f.change.field or '-'}` | `{site.file}:{site.line}` |"
                )

        if ai_insight:
            lines.append(ai_insight)

        lines.extend(
            [
                "\n### 📝 Next Steps",
                "1. Review the inline comments below.",
                "2. Update any deprecated or removed API fields before merging.",
                "\n---",
                "*Generated automatically by [Hound API Watchdog](https://github.com/8dazo/hound)*",
            ]
        )

        return "\n".join(lines)

    def post_to_github_pr(
        self,
        repo: str,
        pr_number: int,
        token: str,
        result: PRReviewResult,
    ) -> Dict[str, Any]:
        """Post the review and inline comments to GitHub PR using the GitHub REST API."""
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

        # 1. Post to PR Issue conversation timeline
        issue_comments_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        payload = {"body": result.summary}
        requests.post(issue_comments_url, headers=headers, json=payload, timeout=15)

        # 2. Also submit formal PR review
        review_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
        review_payload = {
            "body": result.summary,
            "event": "COMMENT",
        }
        review_resp = requests.post(review_url, headers=headers, json=review_payload, timeout=15)
        review_id = review_resp.json().get("id") if review_resp.status_code in (200, 201) else None

        # 3. Post inline comments on diff lines
        comments_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/comments"
        posted_comments = 0

        # Get latest commit ID on PR
        pr_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
        pr_resp = requests.get(pr_url, headers=headers, timeout=10)
        commit_id = (
            pr_resp.json().get("head", {}).get("sha") if pr_resp.status_code == 200 else None
        )

        if commit_id:
            for comment in result.inline_comments:
                c_payload = {
                    "body": comment.body,
                    "commit_id": commit_id,
                    "path": comment.path,
                    "line": comment.line,
                    "side": "RIGHT",
                }
                c_resp = requests.post(comments_url, headers=headers, json=c_payload, timeout=10)
                if c_resp.status_code in (200, 201):
                    posted_comments += 1

        return {
            "status": "success",
            "review_id": review_id,
            "inline_comments_posted": posted_comments,
            "verdict": result.verdict,
        }
