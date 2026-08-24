from hound.models import HoundConfig, WatchTargetConfig
from hound.reviewer.pr_reviewer import PRReviewer


def test_parse_diff_lines():
    diff_sample = """
--- a/src/payments.py
+++ b/src/payments.py
@@ -10,0 +11,3 @@
+import stripe
+res = stripe.Charge.create(source="tok_1", amount=100)
+print(res)
"""
    reviewer = PRReviewer(HoundConfig(watch=[]))
    parsed = reviewer.parse_diff_lines(diff_sample)

    assert "src/payments.py" in parsed
    assert parsed["src/payments.py"] == {11, 12, 13}


def test_pr_reviewer_review_diff(tmp_path):
    spec_file = tmp_path / "stripe_spec.json"
    spec_file.write_text("""
{
    "openapi": "3.0.0",
    "info": {"title": "Stripe", "version": "1.0"},
    "paths": {
        "/v1/charges": {
            "post": {
                "deprecated": true,
                "responses": {"200": {"description": "ok"}}
            }
        }
    }
}
""")

    code_file = tmp_path / "charge.py"
    code_file.write_text("""
import requests
def pay():
    requests.post("https://api.stripe.com/v1/charges")
""")

    cfg = HoundConfig(
        watch=[
            WatchTargetConfig(
                name="stripe",
                spec_url=str(spec_file),
                scan_paths=[str(tmp_path)],
                language="python",
            )
        ]
    )

    reviewer = PRReviewer(cfg)
    changed_lines = {str(code_file): {4}}

    result = reviewer.review_diff(changed_lines)
    assert len(result.findings) >= 1
    assert result.verdict in ("COMMENT", "REQUEST_CHANGES", "APPROVE")
    assert "Hound API Review" in result.summary
