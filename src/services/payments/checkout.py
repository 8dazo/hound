"""Payment checkout service integrating with third-party payment gateways."""

import requests

STRIPE_API_BASE = "https://api.stripe.com"


def process_legacy_charge(amount_cents: int, token: str) -> dict:
    """Process a charge using legacy Stripe charges endpoint."""
    url = f"{STRIPE_API_BASE}/v1/charges"
    payload = {
        "amount": amount_cents,
        "currency": "usd",
        "source": token,
    }
    response = requests.post(url, json=payload, timeout=10)
    data = response.json()
    return {
        "charge_id": data.get("id"),
        "status": data.get("status"),
        "source": data.get("source"),
    }


def process_payment_intent(amount_cents: int) -> dict:
    """Process a modern PaymentIntent."""
    url = f"{STRIPE_API_BASE}/v1/payment_intents"
    payload = {
        "amount": amount_cents,
        "currency": "usd",
    }
    response = requests.post(url, json=payload, timeout=10)
    data = response.json()
    return {
        "intent_id": data.get("id"),
        "status": data.get("status"),
    }
