"""Correlator engine: Intersects OpenAPI changes with actual codebase usage sites."""

from __future__ import annotations

import fnmatch
import re

from hound.models import ChangeRecord, Finding, UsageRecord

SEVERITY_LEVELS = {
    "non_breaking": 0,
    "deprecation": 1,
    "breaking": 2,
}


def normalize_path_template(path: str) -> str:
    """Normalize path parameters in URL templates to {param} for matching."""
    # Convert /v1/charges/{id} or /v1/charges/{charge_id} -> /v1/charges/{_}
    # Also strip trailing slashes
    clean = path.strip().rstrip("/")
    if not clean.startswith("/"):
        clean = "/" + clean
    # Replace any {param_name} with generic placeholder
    return re.sub(r"\{[^}]+\}", "{_}", clean)


def paths_match(spec_path: str, usage_path: str) -> bool:
    """Check if a spec path and a usage path refer to the same endpoint."""
    norm_spec = normalize_path_template(spec_path)
    norm_usage = normalize_path_template(usage_path)

    if norm_spec == norm_usage:
        return True

    # Check regex matching where {param} can match concrete path segments
    # Convert {param} to [^/]+
    regex_pattern = "^" + re.sub(r"\{[^}]+\}", r"[^/]+", spec_path.rstrip("/")) + "$"
    if re.match(regex_pattern, usage_path.rstrip("/")):
        return True

    return False


def is_field_ignored(field_name: str | None, ignore_patterns: list[str]) -> bool:
    """Check if a field name matches any user-configured ignore pattern."""
    if not field_name or not ignore_patterns:
        return False

    for pattern in ignore_patterns:
        if fnmatch.fnmatch(field_name, pattern) or fnmatch.fnmatch(f"*.{field_name}", pattern):
            return True

    return False


def classify_severity(change: ChangeRecord) -> str:
    """Determine severity level of a change record."""
    if change.breaking:
        return "breaking"
    if "deprecated" in change.change_type or "deprecated" in change.description.lower():
        return "deprecation"
    return "non_breaking"


def correlate(
    changes: list[ChangeRecord],
    usage: list[UsageRecord],
    min_severity: str = "breaking",
    ignore_fields: list[str] | None = None,
) -> list[Finding]:
    """Correlate API changes against codebase usage sites to determine blast radius.

    Pure function: no I/O, fully deterministic.
    """
    ignore_list = ignore_fields or []
    min_level = SEVERITY_LEVELS.get(min_severity, 2)
    findings: list[Finding] = []

    for change in changes:
        # Check ignore rules
        if is_field_ignored(change.field, ignore_list):
            continue

        severity = classify_severity(change)
        change_level = SEVERITY_LEVELS.get(severity, 0)

        # Match against usage call-sites
        matching_sites: list[UsageRecord] = []

        for site in usage:
            # Check path match
            if not paths_match(change.endpoint, site.endpoint):
                continue

            # Check method match (ALL matches any method)
            if change.method != "ALL" and site.method != "ALL" and change.method != site.method:
                continue

            # Check field match
            if change.field is None:
                # Endpoint/method level change affects all call sites for this endpoint
                matching_sites.append(site)
            else:
                # Field level change affects sites reading or writing that field
                all_site_fields = set(site.fields_read) | set(site.fields_written)
                if change.field in all_site_fields:
                    matching_sites.append(site)
                elif not all_site_fields:
                    # If static analysis couldn't extract fields, include site as potential match
                    matching_sites.append(site)

        if matching_sites and change_level >= min_level:
            reason = _build_reason(change, matching_sites)
            findings.append(
                Finding(
                    change=change,
                    usage_sites=matching_sites,
                    severity=severity,
                    reason=reason,
                )
            )

    return findings


def _build_reason(change: ChangeRecord, sites: list[UsageRecord]) -> str:
    """Generate concise human-readable explanation of why this change impacts the code."""
    locs = [f"{s.file}:{s.line}" for s in sites]
    loc_str = ", ".join(locs[:3])
    if len(locs) > 3:
        loc_str += f" and {len(locs) - 3} more"

    if change.field:
        return f"Field `{change.field}` on `{change.endpoint}` is used in {loc_str}"
    return f"Endpoint `{change.method} {change.endpoint}` is called in {loc_str}"
