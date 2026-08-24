"""GitHub Issues reporting backend."""

from __future__ import annotations

import os
from typing import Any

import requests

from hound.models import Finding, GitHubIssuesConfig


class GitHubIssueReporter:
    """Formats and posts findings as GitHub Issues idempotently."""

    def __init__(self, config: GitHubIssuesConfig) -> None:
        self.config = config

    def format_issue_title(self, target_name: str, findings: list[Finding]) -> str:
        breaking_count = sum(1 for f in findings if f.is_breaking)
        if breaking_count > 0:
            return f"🐕 Hound: {breaking_count} breaking API change{'s' if breaking_count != 1 else ''} detected in `{target_name}`"
        return f"🐕 Hound: API update notice for `{target_name}` ({len(findings)} changes)"

    def format_issue_body(
        self, target_name: str, findings: list[Finding], content_hash: str
    ) -> str:
        """Construct full markdown body for the GitHub Issue."""
        body_lines = [
            "## 🐕 Hound API Watchdog Alert",
            "",
            f"Hound detected API specification changes for **`{target_name}`** that intersect with your codebase usage.",
            "",
            "### 💥 Blast Radius Summary",
            "",
            "| Severity | Method | Endpoint | Field | Affected Locations |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]

        for f in findings:
            sev_badge = "🔴 `BREAKING`" if f.is_breaking else f"🟡 `{f.severity.upper()}`"
            field_name = f"`{f.change.field}`" if f.change.field else "*(all)*"
            locs = "<br>".join([f"`{u.file}:{u.line}`" for u in f.usage_sites])
            body_lines.append(
                f"| {sev_badge} | `{f.change.method}` | `{f.change.endpoint}` | {field_name} | {locs} |"
            )

        body_lines.extend(
            [
                "",
                "### 🔍 Detailed Findings",
                "",
            ]
        )

        for i, f in enumerate(findings, 1):
            body_lines.extend(
                [
                    f"#### {i}. {f.change.method} `{f.change.endpoint}`"
                    + (f" (field: `{f.change.field}`)" if f.change.field else ""),
                    f"- **Change Type**: `{f.change.change_type}`",
                    f"- **Description**: {f.change.description}",
                    f"- **Why your code is affected**: {f.reason}",
                    "- **Call Sites in Codebase**:",
                ]
            )
            for site in f.usage_sites:
                body_lines.append(
                    f"  - `{site.file}:{site.line}` (read: `{site.fields_read}`, written: `{site.fields_written}`)"
                )

            if f.source_excerpt:
                body_lines.extend(
                    [
                        "- **Source Excerpt**:",
                        "  ```",
                        f"  {f.source_excerpt.strip()}",
                        "  ```",
                    ]
                )
            body_lines.append("")

        body_lines.extend(
            [
                "---",
                f"*Generated automatically by [Hound](https://github.com/8dazo/hound) · Spec Hash: `{content_hash[:12]}`*",
                f"<!-- hound-hash:{content_hash} -->",
            ]
        )

        return "\n".join(body_lines)

    def publish(
        self,
        target_name: str,
        findings: list[Finding],
        content_hash: str,
        dry_run: bool = False,
    ) -> dict[str, Any] | None:
        """Post or update GitHub issue idempotently."""
        if not findings:
            return None

        title = self.format_issue_title(target_name, findings)
        body = self.format_issue_body(target_name, findings, content_hash)

        if dry_run or not self.config.enabled:
            return {"dry_run": True, "title": title, "body": body}

        repo = self.config.repo or os.environ.get("GITHUB_REPOSITORY")
        token = self.config.token or os.environ.get("GITHUB_TOKEN")

        if not repo or not token:
            raise ValueError(
                "GitHub Issues reporting enabled but repo or token not provided (GITHUB_REPOSITORY / GITHUB_TOKEN)"
            )

        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

        # Check existing issues to prevent duplicates
        target_label = f"hound:{target_name}"
        labels = list(set(self.config.labels + [target_label]))
        search_url = f"https://api.github.com/repos/{repo}/issues"
        params = {"state": "open", "labels": target_label}

        try:
            get_resp = requests.get(search_url, headers=headers, params=params, timeout=15.0)
            if get_resp.status_code == 200:
                open_issues = get_resp.json()
                for issue in open_issues:
                    if f"<!-- hound-hash:{content_hash} -->" in (issue.get("body") or ""):
                        # Already reported with exact spec content hash
                        return {"action": "existing_skipped", "issue_url": issue.get("html_url")}

                    # Update existing open issue for this target
                    issue_number = issue.get("number")
                    patch_url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
                    patch_resp = requests.patch(
                        patch_url,
                        headers=headers,
                        json={"title": title, "body": body, "labels": labels},
                        timeout=15.0,
                    )
                    patch_resp.raise_for_status()
                    return {"action": "updated", "issue_url": patch_resp.json().get("html_url")}

            # Create new issue
            payload = {
                "title": title,
                "body": body,
                "labels": labels,
            }
            if self.config.assignees:
                payload["assignees"] = self.config.assignees

            post_resp = requests.post(search_url, headers=headers, json=payload, timeout=15.0)
            post_resp.raise_for_status()
            return {"action": "created", "issue_url": post_resp.json().get("html_url")}

        except Exception as e:
            raise RuntimeError(f"Failed to publish GitHub issue: {e}") from e
