from hound.usage_scanner.ast_scanner import ASTScanner


def test_scan_requests_call_with_field_extraction(tmp_path):
    code = """
import requests

def make_charge():
    resp = requests.post("https://api.stripe.com/v1/charges", json={"amount": 500, "source": "tok_123"})
    data = resp.json()
    print(data["source"])
    return data.get("id")
"""
    file_path = tmp_path / "charge_service.py"
    file_path.write_text(code)

    scanner = ASTScanner()
    records = scanner.scan_file(file_path)

    assert len(records) == 1
    r = records[0]
    assert r.endpoint == "/v1/charges"
    assert r.method == "POST"
    assert "amount" in r.fields_written
    assert "source" in r.fields_written
    assert "source" in r.fields_read
    assert "id" in r.fields_read
    assert r.line == 5


def test_scan_sdk_call(tmp_path):
    code = """
import stripe

def create_payment():
    charge = stripe.Charge.create(amount=2000, currency="usd", source="tok_visa")
    return charge.id
"""
    file_path = tmp_path / "sdk_charge.py"
    file_path.write_text(code)

    scanner = ASTScanner()
    records = scanner.scan_file(file_path)

    assert len(records) == 1
    r = records[0]
    assert r.endpoint == "/v1/charges"
    assert r.method == "POST"
    assert "amount" in r.fields_written
    assert "source" in r.fields_written
    assert "id" in r.fields_read
