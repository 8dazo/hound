"""Slack webhook notification reporter."""

from __future__ import annotations

import os
from typing import Any

import requests

from hound.models import Finding, SlackConfig


class SlackReporter:
    """Formats and posts alerts to Slack incoming webhooks."""

    def __init__(self, config: SlackConfig) -> None:
        self.config = config

    def format_payload(self, target_name: str, findings: list[Finding]) -> dict[str, Any]:
        breaking_count = sum(1 for f in findings if f.is_breaking)
        color = "#E01E5A" if breaking_count > 0 else "#ECB22E"

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🐕 Hound Alert: API changes in {target_name}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Hound found *{len(findings)} relevant API change(s)* ({breaking_count} breaking) that impact your codebase.",
                },
            },
            {"type": "divider"},
        ]

        for f in findings[:5]:
            icon = "🔴" if f.is_breaking else "🟡"
            locs = ", ".join([f"`{u.file}:{u.line}`" for u in f.usage_sites])
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{icon} *{f.change.method} {f.change.endpoint}*\n"
                        f"• Change: {f.change.description}\n"
                        f"• Used in: {locs}",
                    },
                }
            )

        if len(findings) > 5:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"_+ {len(findings) - 5} more findings omitted for brevity._",
                        }
                    ],
                }
            )

        return {"attachments": [{"color": color, "blocks": blocks}]}

    def publish(
        self,
        target_name: str,
        findings: list[Finding],
        dry_run: bool = False,
    ) -> dict[str, Any] | None:
        """Send message to configured Slack webhook URL."""
        if not findings or not self.config.enabled:
            return None

        webhook_url = self.config.webhook_url or os.environ.get("SLACK_WEBHOOK_URL")
        payload = self.format_payload(target_name, findings)

        if dry_run or not webhook_url:
            return {"dry_run": True, "payload": payload}

        try:
            resp = requests.post(webhook_url, json=payload, timeout=10.0)
            resp.raise_for_status()
            return {"action": "sent", "status_code": resp.status_code}
        except Exception as e:
            raise RuntimeError(f"Failed to post to Slack webhook: {e}") from e
