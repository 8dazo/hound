"""Payment charge service."""

import requests

BASE_URL = "https://api.stripe.com"


def create_customer_charge(amount: int, currency: str, source: str) -> dict:
    """Create a charge using legacy source parameter."""
    url = f"{BASE_URL}/v1/charges"
    payload = {
        "amount": amount,
        "currency": currency,
        "source": source,
    }

    # Line 18: API call site
    resp = requests.post(url, json=payload)
    resp.raise_for_status()
    charge_data = resp.json()

    # Reading the source field from the response
    source_id = charge_data["source"]
    charge_id = charge_data.get("id")

    return {
        "id": charge_id,
        "source": source_id,
        "amount": charge_data["amount"],
    }
