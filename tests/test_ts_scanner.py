from hound.usage_scanner.ts_scanner import TSScanner


def test_ts_scanner_axios_and_destructuring(tmp_path):
    ts_code = """
import axios from 'axios';

export async function processPayment(amount: number, source: string) {
    const response = await axios.post('https://api.stripe.com/v1/charges', {
        amount,
        currency: 'usd',
        source,
    });

    const { id, status } = response.data;
    console.log(response.data.source);
    return { id, status };
}
"""
    file_path = tmp_path / "paymentService.ts"
    file_path.write_text(ts_code)

    scanner = TSScanner()
    records = scanner.scan_file(file_path)

    assert len(records) == 1
    r = records[0]
    assert r.endpoint == "/v1/charges"
    assert r.method == "POST"
    assert "amount" in r.fields_written
    assert "source" in r.fields_written
    assert "currency" in r.fields_written
    assert "source" in r.fields_read
    assert "id" in r.fields_read
    assert r.line == 5


def test_ts_scanner_fetch(tmp_path):
    ts_code = """
async function createCustomer() {
    const res = await fetch('https://api.stripe.com/v1/customers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: 'user@example.com', name: 'Alice' })
    });
    return res.json();
}
"""
    file_path = tmp_path / "customer.ts"
    file_path.write_text(ts_code)

    scanner = TSScanner()
    records = scanner.scan_file(file_path)

    assert len(records) == 1
    assert records[0].endpoint == "/v1/customers"
    assert records[0].method == "POST"
    assert "email" in records[0].fields_written
    assert "name" in records[0].fields_written


def test_ts_scanner_sdk_signature(tmp_path):
    ts_code = """
import Stripe from 'stripe';
const stripe = new Stripe(process.env.STRIPE_KEY!);

export async function chargeCard() {
    const charge = await stripe.charges.create({
        amount: 2000,
        currency: 'usd',
        source: 'tok_visa',
    });
    console.log(charge.source);
    return charge.id;
}
"""
    file_path = tmp_path / "stripeSdk.ts"
    file_path.write_text(ts_code)

    scanner = TSScanner()
    records = scanner.scan_file(file_path)

    assert len(records) == 1
    assert records[0].endpoint == "/v1/charges"
    assert records[0].method == "POST"
    assert "source" in records[0].fields_written
    assert "source" in records[0].fields_read
