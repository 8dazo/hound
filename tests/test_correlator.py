from hound.correlator import correlate, paths_match
from hound.models import ChangeRecord, UsageRecord


def test_paths_match():
    assert paths_match("/v1/charges", "/v1/charges")
    assert paths_match("/v1/charges/{id}", "/v1/charges/{charge_id}")
    assert paths_match("/v1/charges/{id}", "/v1/charges/ch_12345")
    assert not paths_match("/v1/charges", "/v1/customers")


def test_correlate_intersecting_field():
    change = ChangeRecord(
        endpoint="/v1/charges",
        method="POST",
        field="source",
        change_type="field_removed",
        breaking=True,
        description="field source removed",
    )
    usage = UsageRecord(
        endpoint="/v1/charges",
        method="POST",
        fields_read=["source", "id"],
        fields_written=["amount"],
        file="src/payments.py",
        line=42,
    )

    findings = correlate([change], [usage], min_severity="breaking")
    assert len(findings) == 1
    f = findings[0]
    assert f.is_breaking is True
    assert f.change.field == "source"
    assert len(f.usage_sites) == 1
    assert f.usage_sites[0].file == "src/payments.py"


def test_correlate_suppressed_when_field_not_used():
    change = ChangeRecord(
        endpoint="/v1/charges",
        method="POST",
        field="unrelated_field",
        change_type="field_removed",
        breaking=True,
        description="field unrelated_field removed",
    )
    usage = UsageRecord(
        endpoint="/v1/charges",
        method="POST",
        fields_read=["source", "id"],
        fields_written=["amount"],
        file="src/payments.py",
        line=42,
    )

    findings = correlate([change], [usage], min_severity="breaking")
    assert len(findings) == 0


def test_correlate_ignored_fields():
    change = ChangeRecord(
        endpoint="/v1/charges",
        method="POST",
        field="beta_field",
        change_type="field_removed",
        breaking=True,
        description="beta_field removed",
    )
    usage = UsageRecord(
        endpoint="/v1/charges",
        method="POST",
        fields_read=["beta_field"],
        fields_written=[],
        file="src/payments.py",
        line=42,
    )

    findings = correlate([change], [usage], min_severity="breaking", ignore_fields=["*.beta_field"])
    assert len(findings) == 0
