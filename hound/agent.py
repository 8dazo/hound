"""Orchestration agent for Hound: Fetch -> Diff -> Scan -> Correlate -> Report -> Advance Snapshot."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from hound.config import load_config
from hound.correlator import correlate
from hound.diffing.spec_diff import SpecDiffEngine
from hound.fetchers.openapi_fetcher import OpenAPIFetcher
from hound.models import ChangeRecord, Finding, HoundConfig, UsageRecord, WatchTargetConfig
from hound.reporter.github_issue import GitHubIssueReporter
from hound.reporter.slack_notify import SlackReporter
from hound.store.snapshot_store import LocalSnapshotStore, SnapshotStore
from hound.usage_scanner.ast_scanner import ASTScanner

logger = logging.getLogger(__name__)


@dataclass
class TargetCheckResult:
    target_name: str
    is_baseline: bool = False
    is_unchanged: bool = False
    spec_hash: str = ""
    changes: list[ChangeRecord] = field(default_factory=list)
    usage_sites: list[UsageRecord] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    suppressed_count: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class CheckSummary:
    results: list[TargetCheckResult] = field(default_factory=list)
    total_breaking: int = 0
    total_findings: int = 0
    exit_code: int = 0


class HoundAgent:
    """End-to-end Hound orchestration agent."""

    def __init__(
        self,
        config: HoundConfig,
        store: SnapshotStore | None = None,
        diff_engine: SpecDiffEngine | None = None,
        scanner: ASTScanner | None = None,
        fetcher: OpenAPIFetcher | None = None,
    ) -> None:
        self.config = config
        self.store = store or LocalSnapshotStore()
        self.diff_engine = diff_engine or SpecDiffEngine()
        self.scanner = scanner or ASTScanner()
        self.fetcher = fetcher or OpenAPIFetcher()
        self.github_reporter = GitHubIssueReporter(config.report.github_issues)
        self.slack_reporter = SlackReporter(config.report.slack)

    @classmethod
    def from_config_path(cls, path: str | Path = "hound.yaml") -> HoundAgent:
        cfg = load_config(path)
        return cls(config=cfg)

    def run_check(
        self,
        target_filter: str | None = None,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> CheckSummary:
        """Run full check cycle across all configured watch targets."""
        summary = CheckSummary()
        targets = self.config.watch

        if target_filter:
            targets = [t for t in targets if t.name == target_filter]
            if not targets:
                raise ValueError(f"No watch target found matching name '{target_filter}'")

        for target in targets:
            result = self._check_target(target, dry_run=dry_run, verbose=verbose)
            summary.results.append(result)
            summary.total_breaking += sum(1 for f in result.findings if f.is_breaking)
            summary.total_findings += len(result.findings)

        # Set standard exit code: 1 if any breaking changes found, else 0
        summary.exit_code = 1 if summary.total_breaking > 0 else 0
        return summary

    def _check_target(
        self,
        target: WatchTargetConfig,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> TargetCheckResult:
        result = TargetCheckResult(target_name=target.name)

        # 1. Fetch current spec
        fetched = self.fetcher.fetch(target.spec_url)
        result.spec_hash = fetched.content_hash

        # 2. Check snapshot store
        old_spec = self.store.get_snapshot(target.name)
        old_hash = self.store.get_snapshot_hash(target.name)

        # Case A: First run establishes baseline
        if old_spec is None:
            result.is_baseline = True
            if not dry_run:
                self.store.save_snapshot(target.name, fetched.spec, fetched.content_hash)
            return result

        # Case B: Unchanged content hash -> short-circuit
        if old_hash == fetched.content_hash:
            result.is_unchanged = True
            return result

        # Case C: Spec changed! Run diff engine
        changes = self.diff_engine.diff(old_spec, fetched.spec)
        result.changes = changes

        if not changes:
            result.is_unchanged = True
            if not dry_run:
                self.store.save_snapshot(target.name, fetched.spec, fetched.content_hash)
            return result

        # 3. Scan codebase for usage
        usage_records: list[UsageRecord] = []
        for scan_path in target.scan_paths:
            found = self.scanner.scan_directory(scan_path)
            usage_records.extend(found)
        result.usage_sites = usage_records

        if not usage_records:
            result.warnings.append(
                f"Usage scan found zero call sites in configured scan paths: {target.scan_paths}"
            )

        # 4. Correlate spec diff against usage table
        all_findings = correlate(
            changes=changes,
            usage=usage_records,
            min_severity="non_breaking" if verbose else self.config.report.min_severity,
            ignore_fields=target.ignore_fields,
        )

        if verbose:
            result.findings = all_findings
        else:
            # Filter by min_severity
            min_sev = self.config.report.min_severity
            if min_sev == "breaking":
                result.findings = [f for f in all_findings if f.is_breaking]
                result.suppressed_count = len(all_findings) - len(result.findings)
            elif min_sev == "deprecation":
                result.findings = [
                    f for f in all_findings if f.severity in ("breaking", "deprecation")
                ]
                result.suppressed_count = len(all_findings) - len(result.findings)
            else:
                result.findings = all_findings

        # 5. Report (if any actionable findings)
        if result.findings and not dry_run:
            if self.config.report.github_issues.enabled:
                self.github_reporter.publish(
                    target_name=target.name,
                    findings=result.findings,
                    content_hash=fetched.content_hash,
                )
            if self.config.report.slack.enabled:
                self.slack_reporter.publish(
                    target_name=target.name,
                    findings=result.findings,
                )

        # 6. Advance snapshot ONLY after successful report (guarantees idempotency)
        if not dry_run:
            self.store.save_snapshot(target.name, fetched.spec, fetched.content_hash)

        return result
