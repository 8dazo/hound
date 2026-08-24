"""Reporting backends for GitHub Issues, Slack notifications, and console output."""

from hound.reporter.github_issue import GitHubIssueReporter
from hound.reporter.slack_notify import SlackReporter

__all__ = ["GitHubIssueReporter", "SlackReporter"]
