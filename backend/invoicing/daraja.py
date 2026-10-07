"""Sandbox-only adapter for Daraja M-Pesa Express (STK Push)."""

import re
import hashlib
from decimal import Decimal

from django.conf import settings
from mpesa_sdk import (
    Mpesa,
    generate_mpesa_express_password,
    generate_timestamp,
    oauth_generate_token,
)


class DarajaUnavailable(Exception):
    """Raised when sandbox credentials or callback configuration are missing."""


class DarajaError(Exception):
    """Raised when a Daraja response cannot safely be used."""


def is_configured():
    return all(
        (
            settings.DARAJA_ENV == "sandbox",
            settings.DARAJA_CONSUMER_KEY,
            settings.DARAJA_CONSUMER_SECRET,
            settings.DARAJA_SHORTCODE,
            settings.DARAJA_PASSKEY,
            settings.DARAJA_CALLBACK_URL.startswith("https://"),
        )
    )


def normalize_phone_number(value):
    digits = re.sub(r"\D", "", value)
    if digits.startswith("0"):
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits[0] in "17":
        digits = "254" + digits
    if not re.fullmatch(r"254[17]\d{8}", digits):
        raise ValueError("Enter a valid Kenyan M-Pesa number.")
    return digits


def phone_number_digest(value):
    try:
        normalized = normalize_phone_number(str(value))
    except ValueError:
        return None
    return hashlib.sha256(normalized.encode("ascii")).hexdigest()


def _client():
    if not is_configured():
        raise DarajaUnavailable("Daraja sandbox integration is not configured.")
    token_response, status_code = oauth_generate_token(
        settings.DARAJA_CONSUMER_KEY,
        settings.DARAJA_CONSUMER_SECRET,
        env="sandbox",
        timeout=10,
    )
    token = (
        token_response.get("access_token") if isinstance(token_response, dict) else None
    )
    if status_code != 200 or not token:
        raise DarajaError("Daraja sandbox authorization failed.")
    return Mpesa(token, env="sandbox", timeout=10)


def _password_and_timestamp():
    timestamp = generate_timestamp()
    password = generate_mpesa_express_password(
        settings.DARAJA_SHORTCODE, settings.DARAJA_PASSKEY, timestamp
    )
    return password, timestamp


def _safe_response(response):
    allowed = (
        "ResponseCode",
        "ResponseDescription",
        "MerchantRequestID",
        "CheckoutRequestID",
        "ResultCode",
        "ResultDesc",
    )
    return {key: response[key] for key in allowed if key in response}


def initiate_stk_push(attempt):
    client = _client()
    password, timestamp = _password_and_timestamp()
    response, status_code = client.mpesa_express_payment(
        {
            "BusinessShortCode": settings.DARAJA_SHORTCODE,
            "Password": password,
            "Timestamp": timestamp,
            "Amount": int(attempt.amount),
            "PartyA": attempt.phone_number,
            "PartyB": settings.DARAJA_SHORTCODE,
            "PhoneNumber": attempt.phone_number,
            "CallBackURL": settings.DARAJA_CALLBACK_URL,
            "AccountReference": attempt.invoice.invoice_number[:12],
            "TransactionDesc": "Invoice payment",
        }
    )
    if status_code != 200 or response.get("ResponseCode") not in (0, "0"):
        raise DarajaError("Daraja did not accept the M-Pesa Express request.")
    if not response.get("CheckoutRequestID") or not response.get("MerchantRequestID"):
        raise DarajaError("Daraja accepted the request without request identifiers.")
    return _safe_response(response)


def query_stk_push(checkout_request_id):
    client = _client()
    password, timestamp = _password_and_timestamp()
    response, status_code = client.mpesa_express_query(
        {
            "BusinessShortCode": settings.DARAJA_SHORTCODE,
            "Password": password,
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id,
        }
    )
    if status_code != 200:
        raise DarajaError("Daraja could not verify the checkout status.")
    return _safe_response(response)


def is_successful_query(response):
    return str(response.get("ResultCode", "")) == "0"


def is_final_query(response):
    # A missing ResultCode means the checkout is still pending or the response
    # did not contain a transaction result. Never infer success from ResponseCode.
    return response.get("ResultCode") not in (None, "")


def query_matches_attempt(response, attempt):
    """Require the authenticated query to match both provider request IDs."""
    return (
        response.get("CheckoutRequestID") == attempt.checkout_request_id
        and response.get("MerchantRequestID") == attempt.merchant_request_id
        and is_final_query(response)
    )


def callback_matches_success(callback, attempt, query_response):
    """Check callback success and its amount/phone against the immutable attempt."""
    if not query_matches_attempt(query_response, attempt):
        return False
    if str(query_response.get("ResultCode")) != "0":
        return False
    if str(callback.get("ResultCode")) != "0":
        return False
    if callback.get("CheckoutRequestID") != attempt.checkout_request_id:
        return False
    if callback.get("MerchantRequestID") != attempt.merchant_request_id:
        return False

    metadata = callback.get("CallbackMetadata")
    items = metadata.get("Item") if isinstance(metadata, dict) else None
    if not isinstance(items, list):
        return False
    values = {
        item.get("Name"): item.get("Value")
        for item in items
        if isinstance(item, dict) and isinstance(item.get("Name"), str)
    }
    try:
        callback_amount = Decimal(str(values.get("Amount")))
        callback_phone_digest = values.get("PhoneNumberHash")
    except (ArithmeticError, ValueError):
        return False
    expected_phone_digest = phone_number_digest(attempt.phone_number)
    return (
        callback_amount == attempt.amount
        and callback_phone_digest is not None
        and callback_phone_digest == expected_phone_digest
    )


def amount_for_attempt(value):
    amount = Decimal(value)
    if amount <= 0 or amount != amount.to_integral_value():
        raise ValueError("M-Pesa Express payments must be positive whole KES amounts.")
    return amount
