from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from .daraja import (
    DarajaError,
    amount_for_attempt,
    initiate_stk_push,
    normalize_phone_number,
    query_stk_push,
)


@override_settings(
    DARAJA_ENV="sandbox",
    DARAJA_CONSUMER_KEY="sandbox-key",
    DARAJA_CONSUMER_SECRET="sandbox-secret",
    DARAJA_SHORTCODE="174379",
    DARAJA_PASSKEY="sandbox-passkey",
    DARAJA_CALLBACK_URL="https://example.invalid/api/payments/daraja/sandbox/stk/callback/",
)
class DarajaAdapterTests(SimpleTestCase):
    def test_phone_numbers_are_normalized_to_254_country_code(self):
        self.assertEqual(normalize_phone_number("0700000000"), "254700000000")
        self.assertEqual(normalize_phone_number("+254700000000"), "254700000000")
        self.assertEqual(normalize_phone_number("711111111"), "254711111111")
        with self.assertRaises(ValueError):
            normalize_phone_number("12345")

    def test_amount_must_be_positive_whole_kes(self):
        self.assertEqual(amount_for_attempt("5"), Decimal("5"))
        with self.assertRaises(ValueError):
            amount_for_attempt("0")
        with self.assertRaises(ValueError):
            amount_for_attempt("5.5")

    @patch("invoicing.daraja.generate_timestamp", return_value="20261006120000")
    @patch(
        "invoicing.daraja.oauth_generate_token",
        return_value=({"access_token": "sandbox-token"}, 200),
    )
    @patch("invoicing.daraja.Mpesa")
    def test_initiation_uses_mpesa_express_payment(
        self, mpesa_class, _oauth, _timestamp
    ):
        client = Mock()
        client.mpesa_express_payment.return_value = (
            {
                "ResponseCode": "0",
                "MerchantRequestID": "merchant-1",
                "CheckoutRequestID": "ws_CO_1",
                "CustomerMessage": "Sensitive provider detail excluded",
            },
            200,
        )
        mpesa_class.return_value = client
        attempt = SimpleNamespace(
            amount=Decimal("10"),
            phone_number="254700000000",
            invoice=SimpleNamespace(invoice_number="INV-1001"),
        )

        response = initiate_stk_push(attempt)

        mpesa_class.assert_called_once_with("sandbox-token", env="sandbox", timeout=10)
        client.mpesa_express_payment.assert_called_once_with(
            {
                "BusinessShortCode": "174379",
                "Password": "MTc0Mzc5c2FuZGJveC1wYXNza2V5MjAyNjEwMDYxMjAwMDA=",
                "Timestamp": "20261006120000",
                "Amount": 10,
                "PartyA": "254700000000",
                "PartyB": "174379",
                "PhoneNumber": "254700000000",
                "CallBackURL": "https://example.invalid/api/payments/daraja/sandbox/stk/callback/",
                "AccountReference": "INV-1001",
                "TransactionDesc": "Invoice payment",
            }
        )
        self.assertEqual(response["CheckoutRequestID"], "ws_CO_1")
        self.assertNotIn("CustomerMessage", response)
        client.transaction_status_request.assert_not_called()

    @patch("invoicing.daraja.generate_timestamp", return_value="20261006120000")
    @patch(
        "invoicing.daraja.oauth_generate_token",
        return_value=({"access_token": "sandbox-token"}, 200),
    )
    @patch("invoicing.daraja.Mpesa")
    def test_status_check_uses_mpesa_express_query_by_checkout_id(
        self, mpesa_class, _oauth, _timestamp
    ):
        client = Mock()
        client.mpesa_express_query.return_value = (
            {
                "ResponseCode": "0",
                "MerchantRequestID": "merchant-1",
                "CheckoutRequestID": "ws_CO_1",
                "ResultCode": "0",
                "ResultDesc": "Processed",
            },
            200,
        )
        mpesa_class.return_value = client

        response = query_stk_push("ws_CO_1")

        client.mpesa_express_query.assert_called_once_with(
            {
                "BusinessShortCode": "174379",
                "Password": "MTc0Mzc5c2FuZGJveC1wYXNza2V5MjAyNjEwMDYxMjAwMDA=",
                "Timestamp": "20261006120000",
                "CheckoutRequestID": "ws_CO_1",
            }
        )
        client.transaction_status_request.assert_not_called()
        self.assertEqual(response["CheckoutRequestID"], "ws_CO_1")

    @patch(
        "invoicing.daraja.oauth_generate_token",
        return_value=({}, 200),
    )
    def test_invalid_token_response_stops_before_provider_call(self, _oauth):
        with patch("invoicing.daraja.Mpesa") as mpesa_class:
            with self.assertRaises(DarajaError):
                query_stk_push("ws_CO_1")
        mpesa_class.assert_not_called()
