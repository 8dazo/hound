import json

from hound.models import ChangeRecord, Finding, UsageRecord
from hound.reporter.sarif import SARIFExporter


def test_sarif_export():
    finding = Finding(
        change=ChangeRecord(
            endpoint="/v1/charges",
            method="POST",
            field="source",
            change_type="field_removed",
            breaking=True,
            description="Field source was removed from POST /v1/charges",
        ),
        usage_sites=[
            UsageRecord(
                endpoint="/v1/charges",
                method="POST",
                fields_read=["source"],
                fields_written=["amount"],
                file="src/payments.py",
                line=42,
            )
        ],
        severity="breaking",
        reason="Field source used in src/payments.py:42",
    )

    exporter = SARIFExporter()
    sarif_doc = exporter.export([finding], tool_version="0.1.0")

    assert sarif_doc["version"] == "2.1.0"
    assert len(sarif_doc["runs"]) == 1
    run = sarif_doc["runs"][0]
    assert run["tool"]["driver"]["name"] == "Hound"
    assert len(run["results"]) == 1

    res = run["results"][0]
    assert res["level"] == "error"
    assert res["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "src/payments.py"
    assert res["locations"][0]["physicalLocation"]["region"]["startLine"] == 42


def test_sarif_export_json_validity():
    exporter = SARIFExporter()
    json_str = exporter.export_json([])
    parsed = json.loads(json_str)
    assert parsed["version"] == "2.1.0"
    assert parsed["runs"][0]["results"] == []
