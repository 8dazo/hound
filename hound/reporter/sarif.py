"""SARIF (Static Analysis Results Interchange Format) exporter for GitHub Code Scanning."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from hound.models import Finding


class SARIFExporter:
    """Exports Hound findings into SARIF v2.1.0 for GitHub Code Scanning and PR annotations."""

    SARIF_SCHEMA = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"
    SARIF_VERSION = "2.1.0"

    def export(self, findings: List[Finding], tool_version: str = "0.1.0") -> Dict[str, Any]:
        """Convert findings into a standard SARIF JSON document."""
        rules = [
            {
                "id": "HOUND001",
                "name": "BreakingAPIChange",
                "shortDescription": {
                    "text": "A third-party API introduced a breaking specification change"
                },
                "fullDescription": {
                    "text": "A field, method, or endpoint used by this codebase was removed, renamed, or modified incompatibly."
                },
                "defaultConfiguration": {"level": "error"},
            },
            {
                "id": "HOUND002",
                "name": "DeprecatedAPIUsage",
                "shortDescription": {
                    "text": "A third-party API field or endpoint used by this codebase has been deprecated"
                },
                "fullDescription": {
                    "text": "The vendor marked an endpoint or field as deprecated and it may be removed in a future release."
                },
                "defaultConfiguration": {"level": "warning"},
            },
        ]

        results = []
        for finding in findings:
            rule_id = "HOUND001" if finding.is_breaking else "HOUND002"
            level = (
                "error"
                if finding.is_breaking
                else ("warning" if finding.severity == "deprecation" else "note")
            )

            for site in finding.usage_sites:
                results.append(
                    {
                        "ruleId": rule_id,
                        "level": level,
                        "message": {"text": f"{finding.change.description} ({finding.reason})"},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {
                                        "uri": site.file.replace("\\", "/"),
                                        "uriBaseId": "%SRCROOT%",
                                    },
                                    "region": {
                                        "startLine": max(1, site.line),
                                        "startColumn": 1,
                                    },
                                }
                            }
                        ],
                    }
                )

        return {
            "$schema": self.SARIF_SCHEMA,
            "version": self.SARIF_VERSION,
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "Hound",
                            "version": tool_version,
                            "informationUri": "https://github.com/8dazo/hound",
                            "rules": rules,
                        }
                    },
                    "results": results,
                }
            ],
        }

    def export_json(
        self, findings: List[Finding], tool_version: str = "0.1.0", indent: int = 2
    ) -> str:
        """Export as formatted JSON string."""
        return json.dumps(self.export(findings, tool_version), indent=indent)
