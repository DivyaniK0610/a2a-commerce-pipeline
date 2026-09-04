"""
razorpay_client.py — Razorpay REST API wrapper (no SDK, uses requests directly)
A2A Commerce Pipeline | Razorpay Buildathon Track 1
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

RAZORPAY_BASE_URL = "https://api.razorpay.com/v1"


def _get_auth():
    """Returns (key_id, key_secret) tuple for HTTP Basic Auth."""
    key_id = os.getenv("RAZORPAY_KEY_ID")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        raise EnvironmentError(
            "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set in .env"
        )
    return (key_id, key_secret)


def create_razorpay_order(amount_inr: float, currency: str = "INR",
                          receipt: str = None, notes: dict = None) -> dict:
    """
    Creates a Razorpay order via REST API.
    amount_inr: total amount in INR (converted to paise internally).
    Returns the full Razorpay order dict.
    """
    amount_paise = int(round(amount_inr * 100))

    payload = {
        "amount": amount_paise,
        "currency": currency,
        "receipt": receipt or "rcpt_a2a_order",
        "notes": notes or {},
        "payment_capture": 1
    }

    resp = requests.post(
        f"{RAZORPAY_BASE_URL}/orders",
        json=payload,
        auth=_get_auth(),
        timeout=15
    )
    resp.raise_for_status()
    return resp.json()


def create_payment_link(amount_inr: float, description: str,
                        customer_name: str = None, customer_email: str = None,
                        customer_contact: str = None) -> dict:
    """
    Creates a Razorpay Payment Link via REST API.
    Returns the full response dict — short_url contains the rzp.io link.
    """
    amount_paise = int(round(amount_inr * 100))

    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "accept_partial": False,
        "description": description,
        "notify": {
            "sms": False,
            "email": bool(customer_email)
        },
        "reminder_enable": False,
    }

    if customer_name or customer_email or customer_contact:
        payload["customer"] = {}
        if customer_name:
            payload["customer"]["name"] = customer_name
        if customer_email:
            payload["customer"]["email"] = customer_email
        if customer_contact:
            payload["customer"]["contact"] = customer_contact

    resp = requests.post(
        f"{RAZORPAY_BASE_URL}/payment_links",
        json=payload,
        auth=_get_auth(),
        timeout=15
    )

    if not resp.ok:
        # Log the full Razorpay error for debugging
        error_body = {}
        try:
            error_body = resp.json()
        except Exception:
            error_body = {"raw": resp.text}
        print(f"[RAZORPAY ERROR] Status {resp.status_code}: {error_body}")
        raise Exception(f"Razorpay {resp.status_code}: {error_body}")

    return resp.json()
