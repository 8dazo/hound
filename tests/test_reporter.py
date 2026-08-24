from hound.models import ChangeRecord, Finding, GitHubIssuesConfig, SlackConfig, UsageRecord
from hound.reporter.github_issue import GitHubIssueReporter
from hound.reporter.slack_notify import SlackReporter


def test_github_reporter_format():
    config = GitHubIssuesConfig(enabled=True, repo="org/repo")
    reporter = GitHubIssueReporter(config)

    finding = Finding(
        change=ChangeRecord(
            endpoint="/v1/charges",
            method="POST",
            field="source",
            change_type="field_removed",
            breaking=True,
            description="Field source was removed",
        ),
        usage_sites=[
            UsageRecord(
                endpoint="/v1/charges",
                method="POST",
                fields_read=["source"],
                fields_written=["amount", "source"],
                file="src/charge.py",
                line=25,
            )
        ],
        severity="breaking",
        reason="Field `source` used in src/charge.py:25",
    )

    title = reporter.format_issue_title("stripe", [finding])
    assert "1 breaking API change" in title
    assert "stripe" in title

    body = reporter.format_issue_body("stripe", [finding], content_hash="abcdef123456")
    assert "Blast Radius Summary" in body
    assert "src/charge.py:25" in body
    assert "<!-- hound-hash:abcdef123456 -->" in body

    # Test dry run publish
    pub = reporter.publish("stripe", [finding], content_hash="abcdef123456", dry_run=True)
    assert pub["dry_run"] is True


def test_slack_reporter_format():
    config = SlackConfig(enabled=True, webhook_url="https://hooks.slack.com/services/xxx")
    reporter = SlackReporter(config)

    finding = Finding(
        change=ChangeRecord(
            endpoint="/v1/charges",
            method="POST",
            field="source",
            change_type="field_removed",
            breaking=True,
            description="Field source was removed",
        ),
        usage_sites=[
            UsageRecord(
                endpoint="/v1/charges",
                method="POST",
                fields_read=["source"],
                fields_written=[],
                file="src/charge.py",
                line=25,
            )
        ],
        severity="breaking",
        reason="Field `source` used in src/charge.py:25",
    )

    payload = reporter.format_payload("stripe", [finding])
    assert "attachments" in payload
    assert len(payload["attachments"][0]["blocks"]) > 0

    pub = reporter.publish("stripe", [finding], dry_run=True)
    assert pub["dry_run"] is True
