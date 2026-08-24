"""Core data models for Hound."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChangeRecord(BaseModel):
    """Represents a discrete structural or semantic change detected between two API spec versions."""

    endpoint: str  # e.g. "/v1/charges"
    method: str = "ALL"  # e.g. "POST", "GET", "ALL"
    field: str | None = None  # e.g. "source", "amount"
    change_type: str  # e.g. "field_removed", "endpoint_removed", "type_changed"
    breaking: bool = True  # whether the change breaks backwards compatibility
    description: str = ""  # human-readable explanation
    raw: dict[str, Any] = Field(default_factory=dict)  # raw diff payload for auditability


class UsageRecord(BaseModel):
    """Represents a call-site found in the scanned codebase."""

    endpoint: str  # normalized endpoint e.g. "/v1/charges" or path template
    method: str = "ALL"  # HTTP method e.g. "POST", "GET", "ALL"
    fields_read: list[str] = Field(default_factory=list)  # fields accessed on response
    fields_written: list[str] = Field(default_factory=list)  # fields sent in request payload
    file: str  # relative file path e.g. "src/services/payments/charge.py"
    line: int  # 1-indexed line number


class Finding(BaseModel):
    """Represents an actionable intersection between a spec change and actual codebase usage."""

    change: ChangeRecord
    usage_sites: list[UsageRecord]
    severity: str  # "breaking" | "deprecation" | "non_breaking"
    reason: str = ""
    source_excerpt: str | None = None  # attached for auditability if LLM-assisted

    @property
    def is_breaking(self) -> bool:
        return self.severity == "breaking"


class WatchTargetConfig(BaseModel):
    """Configuration for a single watched API target."""

    name: str
    spec_url: str
    scan_paths: list[str]
    language: str = "python"
    ignore_fields: list[str] = Field(default_factory=list)


class GitHubIssuesConfig(BaseModel):
    """Configuration for GitHub Issues reporting."""

    enabled: bool = True
    repo: str | None = None
    token: str | None = None
    labels: list[str] = Field(default_factory=lambda: ["hound", "dependency-risk"])
    assignees: list[str] = Field(default_factory=list)


class SlackConfig(BaseModel):
    """Configuration for Slack webhook reporting."""

    enabled: bool = False
    webhook_url: str | None = None


class ReportConfig(BaseModel):
    """Configuration for reporting channels and alert thresholds."""

    github_issues: GitHubIssuesConfig = Field(default_factory=GitHubIssuesConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    min_severity: str = "breaking"  # "breaking" | "deprecation" | "non_breaking"


class LLMConfig(BaseModel):
    """Configuration for LLM-assisted prose classification."""

    provider: str = "none"  # "none" | "openai" | "azure_openai" | "huggingface_local"
    model: str = "gpt-4o-mini"
    api_key: str | None = None
    api_base: str | None = None


class HoundConfig(BaseModel):
    """Top-level Hound configuration file model (hound.yaml)."""

    version: int = 1
    watch: list[WatchTargetConfig] = Field(default_factory=list)
    report: ReportConfig = Field(default_factory=ReportConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
