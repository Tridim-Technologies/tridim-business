import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization
from customers.models import Customer
from quotations.models import Job, Quotation, QuotationLine

from .models import (
    DarajaCallbackEvent,
    DarajaPaymentAttempt,
    Invoice,
    Payment,
    PaymentAllocation,
)


class PaymentWorkflowTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.finance = user_model.objects.create_user(
            username="payment-finance", password="a-long-test-password"
        )
        self.sales = user_model.objects.create_user(
            username="payment-sales", password="a-long-test-password"
        )
        self.outsider = user_model.objects.create_user(
            username="payment-outsider", password="a-long-test-password"
        )
        self.organization = Organization.objects.create(name="Payment Org")
        self.other_organization = Organization.objects.create(name="Other Payment Org")
        Membership.objects.create(
            user=self.finance,
            organization=self.organization,
            role=Membership.Role.FINANCE,
        )
        Membership.objects.create(
            user=self.sales,
            organization=self.organization,
            role=Membership.Role.SALES,
        )
        Membership.objects.create(
            user=self.outsider,
            organization=self.other_organization,
            role=Membership.Role.FINANCE,
        )
        self.customer = Customer.objects.create(
            organization=self.organization,
            name="Payment Customer",
            created_by=self.finance,
        )
        self.invoice = self.create_invoice(self.customer, total=Decimal("12.02250"))
        self.payments_url = reverse("payments", args=[self.organization.pk])
        self.list_url = reverse("invoices", args=[self.organization.pk])

    def create_invoice(self, customer, total=Decimal("10.00000"), currency="KES"):
        quotation = Quotation.objects.create(
            organization=customer.organization,
            customer=customer,
            currency=currency,
            valid_until=timezone.localdate() + timedelta(days=14),
            created_by=self.finance,
            status=Quotation.Status.ACCEPTED,
        )
        QuotationLine.objects.create(
            quotation=quotation,
            description="Consulting",
            quantity=Decimal("1.000"),
            unit_price=total,
            position=0,
        )
        job = Job.objects.create(
            organization=customer.organization,
            customer=customer,
            source_quotation=quotation,
            status=Job.Status.COMPLETED,
            created_by=self.finance,
        )
        return Invoice.objects.create(
            organization=customer.organization,
            job=job,
            source_quotation=quotation,
            customer=customer,
            customer_name=customer.name,
            invoice_number=f"PAY-{uuid4().hex[:12]}",
            status=Invoice.Status.ISSUED,
            issue_date=timezone.localdate(),
            due_date=timezone.localdate() + timedelta(days=30),
            currency=currency,
            total=total,
            issued_by=self.finance,
        )

    def post_json(self, url, payload, user=None, headers=None):
        self.client.force_login(user or self.finance)
        return self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
            headers=headers or {},
        )

    def record_payment(self, amount="15.00000", key=None, **overrides):
        idempotency_key = key or uuid4()
        payload = {
            "customer": self.customer.pk,
            "received_date": timezone.localdate().isoformat(),
            "amount": amount,
            "currency": "KES",
            "method": "mobile_money",
            "reference": "receipt-100",
            **overrides,
        }
        response = self.post_json(
            self.payments_url,
            payload,
            headers={"Idempotency-Key": str(idempotency_key)},
        )
        return response, idempotency_key, payload

    def allocate(self, payment_id, invoice_id, amount):
        return self.post_json(
            reverse("payment-allocate", args=[self.organization.pk, payment_id]),
            {"invoice": str(invoice_id), "amount": amount},
        )

    def test_manual_payment_idempotency_and_role_scoping(self):
        key = uuid4()
        response, _, payload = self.record_payment(key=key)
        repeated, _, _ = self.record_payment(key=key)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(repeated.status_code, 200, repeated.content)
        self.assertEqual(response.json()["id"], repeated.json()["id"])
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(response.json()["allocated_total"], "0.00000")
        self.assertEqual(response.json()["unapplied_total"], "15.00000")
        self.customer.name = "Renamed Payment Customer"
        self.customer.save(update_fields=["name"])
        self.assertEqual(
            self.client.get(self.payments_url).json()["results"][0]["customer_name"],
            "Payment Customer",
        )

        conflict = self.record_payment(key=key, amount="14.00000")[0]
        self.assertEqual(conflict.status_code, 409)
        self.client.force_login(self.sales)
        self.assertEqual(self.client.get(self.payments_url).status_code, 403)
        wrong_org = reverse("payments", args=[self.other_organization.pk])
        self.assertEqual(self.client.get(wrong_org).status_code, 404)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.payments_url).status_code, 404)
        self.assertEqual(payload["amount"], "15.00000")

    def test_partial_allocation_overpayment_and_derived_invoice_balance(self):
        payment = self.record_payment()[0].json()
        first = self.allocate(payment["id"], self.invoice.pk, "4.00001")
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(first.json()["allocated_total"], "4.00001")
        self.assertEqual(first.json()["unapplied_total"], "10.99999")

        too_much_for_invoice = self.allocate(payment["id"], self.invoice.pk, "8.02250")
        self.assertEqual(too_much_for_invoice.status_code, 409)
        self.assertEqual(PaymentAllocation.objects.count(), 1)

        final_amount = self.allocate(payment["id"], self.invoice.pk, "8.02249")
        self.assertEqual(final_amount.status_code, 200, final_amount.content)
        self.assertEqual(final_amount.json()["unapplied_total"], "2.97750")
        invoice = self.client.get(self.list_url).json()["results"][0]
        self.assertEqual(invoice["allocated_total"], "12.02250")
        self.assertEqual(invoice["outstanding_total"], "0.00000")
        self.assertEqual(invoice["payment_state"], "paid")

    def test_payment_can_allocate_across_invoices_for_same_customer(self):
        other_invoice = self.create_invoice(self.customer, total=Decimal("5.00000"))
        payment = self.record_payment(amount="20.00000")[0].json()
        first = self.allocate(payment["id"], self.invoice.pk, "12.02250")
        second = self.allocate(payment["id"], other_invoice.pk, "5.00000")
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(second.json()["allocated_total"], "17.02250")
        self.assertEqual(second.json()["unapplied_total"], "2.97750")

    def test_customer_currency_and_tenant_mismatches_are_rejected(self):
        payment = self.record_payment()[0].json()
        other_customer = Customer.objects.create(
            organization=self.organization,
            name="Different Customer",
            created_by=self.finance,
        )
        other_invoice = self.create_invoice(other_customer)
        mismatch = self.allocate(payment["id"], other_invoice.pk, "1.00000")
        self.assertEqual(mismatch.status_code, 400)
        self.assertEqual(PaymentAllocation.objects.count(), 0)

        other_currency_invoice = self.create_invoice(
            self.customer, currency="USD", total=Decimal("9.00000")
        )
        currency_mismatch = self.allocate(
            payment["id"], other_currency_invoice.pk, "1.00000"
        )
        self.assertEqual(currency_mismatch.status_code, 400)
        other_org_invoice = self.create_invoice_for_other_org()
        tenant_mismatch = self.allocate(payment["id"], other_org_invoice.pk, "1.00000")
        self.assertEqual(tenant_mismatch.status_code, 404)
        self.assertEqual(PaymentAllocation.objects.count(), 0)

    def create_invoice_for_other_org(self):
        other_customer = Customer.objects.create(
            organization=self.other_organization,
            name="Outside Customer",
            created_by=self.outsider,
        )
        other_invoice = self.create_invoice(other_customer)
        return other_invoice

    def test_allocation_and_payment_reversals_are_explicit_and_gate_void(self):
        payment = self.record_payment(amount="20.00000")[0].json()
        allocated = self.allocate(payment["id"], self.invoice.pk, "12.02250").json()
        void_url = reverse("invoice-void", args=[self.organization.pk, self.invoice.pk])
        blocked_void = self.post_json(void_url, {"reason": "Correction"})
        self.assertEqual(blocked_void.status_code, 409)

        reverse_payment_url = reverse(
            "payment-reverse", args=[self.organization.pk, payment["id"]]
        )
        blocked_payment_reversal = self.post_json(
            reverse_payment_url, {"reason": "Incorrect receipt"}
        )
        self.assertEqual(blocked_payment_reversal.status_code, 409)

        allocation = PaymentAllocation.objects.get(pk=allocated["allocations"][0]["id"])
        reverse_allocation_url = reverse(
            "payment-allocation-reverse", args=[self.organization.pk, allocation.pk]
        )
        reversed_allocation = self.post_json(
            reverse_allocation_url, {"reason": "Applied to wrong invoice"}
        )
        self.assertEqual(reversed_allocation.status_code, 200)
        self.assertEqual(reversed_allocation.json()["unapplied_total"], "20.00000")
        allocation.refresh_from_db()
        self.assertEqual(allocation.reversed_by, self.finance)
        self.assertEqual(allocation.reversal_reason, "Applied to wrong invoice")

        reversed_payment = self.post_json(
            reverse_payment_url, {"reason": "Receipt was duplicated at source"}
        )
        self.assertEqual(reversed_payment.status_code, 200)
        self.assertEqual(reversed_payment.json()["reversed_by"], self.finance.username)
        self.assertEqual(reversed_payment.json()["unapplied_total"], "0.00000")
        invoice = self.client.get(self.list_url).json()["results"][0]
        self.assertEqual(invoice["outstanding_total"], "12.02250")
        self.assertEqual(invoice["payment_state"], "unpaid")
        self.assertEqual(
            self.post_json(void_url, {"reason": "Correction"}).status_code, 200
        )

    def test_void_invoice_and_reversed_payment_cannot_be_allocated(self):
        payment = self.record_payment()[0].json()
        self.post_json(
            reverse("invoice-void", args=[self.organization.pk, self.invoice.pk]),
            {"reason": "Issued in error"},
        )
        void_invoice_attempt = self.allocate(payment["id"], self.invoice.pk, "1.00000")
        self.assertEqual(void_invoice_attempt.status_code, 409)
        reversed_payment = self.post_json(
            reverse("payment-reverse", args=[self.organization.pk, payment["id"]]),
            {"reason": "Received in error"},
        )
        self.assertEqual(reversed_payment.status_code, 200)
        second_invoice = self.create_invoice(self.customer, total=Decimal("5.00000"))
        reversed_attempt = self.allocate(payment["id"], second_invoice.pk, "1.00000")
        self.assertEqual(reversed_attempt.status_code, 409)

    @override_settings(
        DARAJA_CONSUMER_KEY="sandbox-key",
        DARAJA_CONSUMER_SECRET="sandbox-secret",
        DARAJA_SHORTCODE="174379",
        DARAJA_PASSKEY="sandbox-passkey",
        DARAJA_CALLBACK_URL="https://example.invalid/api/payments/daraja/sandbox/stk/callback/",
    )
    @patch("invoicing.views.initiate_stk_push")
    def test_daraja_attempt_is_idempotent_and_reserves_invoice_balance(self, initiate):
        initiate.return_value = {
            "ResponseCode": "0",
            "MerchantRequestID": "merchant-1",
            "CheckoutRequestID": "ws_CO_1",
        }
        url = reverse(
            "daraja-attempt-create", args=[self.organization.pk, self.invoice.pk]
        )
        key = uuid4()
        payload = {"amount": "8", "phone_number": "+254700000000"}
        first = self.post_json(url, payload, headers={"Idempotency-Key": str(key)})
        repeated = self.post_json(url, payload, headers={"Idempotency-Key": str(key)})
        self.assertEqual(first.status_code, 202, first.content)
        self.assertEqual(repeated.status_code, 202, repeated.content)
        self.assertEqual(first.json()["id"], repeated.json()["id"])
        self.assertEqual(initiate.call_count, 1)
        attempt = DarajaPaymentAttempt.objects.get(pk=first.json()["id"])
        self.assertEqual(attempt.phone_number, "254700000000")

        conflict = self.post_json(
            url,
            {"amount": "8", "phone_number": "254711111111"},
            headers={"Idempotency-Key": str(key)},
        )
        over_reserved = self.post_json(
            url,
            {"amount": "5", "phone_number": "254700000000"},
            headers={"Idempotency-Key": str(uuid4())},
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(over_reserved.status_code, 409)
        self.assertEqual(initiate.call_count, 1)

    @override_settings(
        DARAJA_CONSUMER_KEY="sandbox-key",
        DARAJA_CONSUMER_SECRET="sandbox-secret",
        DARAJA_SHORTCODE="174379",
        DARAJA_PASSKEY="sandbox-passkey",
        DARAJA_CALLBACK_URL="https://example.invalid/api/payments/daraja/sandbox/stk/callback/",
    )
    def test_daraja_requires_sandbox_configuration_kes_and_whole_amount(self):
        url = reverse(
            "daraja-attempt-create", args=[self.organization.pk, self.invoice.pk]
        )
        with patch("invoicing.views.initiate_stk_push") as initiate:
            fractional = self.post_json(
                url,
                {"amount": "1.50", "phone_number": "0700000000"},
                headers={"Idempotency-Key": str(uuid4())},
            )
        self.assertEqual(fractional.status_code, 400)
        initiate.assert_not_called()

        usd_invoice = self.create_invoice(
            self.customer, total=Decimal("10.00000"), currency="USD"
        )
        usd_url = reverse(
            "daraja-attempt-create", args=[self.organization.pk, usd_invoice.pk]
        )
        with patch("invoicing.views.initiate_stk_push") as initiate:
            unsupported_currency = self.post_json(
                usd_url,
                {"amount": "5", "phone_number": "0700000000"},
                headers={"Idempotency-Key": str(uuid4())},
            )
        self.assertEqual(unsupported_currency.status_code, 400)
        initiate.assert_not_called()

        with override_settings(DARAJA_ENV="production"):
            live_disabled = self.post_json(
                url,
                {"amount": "5", "phone_number": "0700000000"},
                headers={"Idempotency-Key": str(uuid4())},
            )
        self.assertEqual(live_disabled.status_code, 503)

    def test_daraja_callback_is_ignored_when_sandbox_is_not_configured(self):
        callback = {
            "Body": {
                "stkCallback": {
                    "CheckoutRequestID": "unconfigured-checkout",
                    "MerchantRequestID": "unconfigured-merchant",
                    "ResultCode": 0,
                }
            }
        }
        response = self.client.post(
            reverse("daraja-stk-callback"),
            data=json.dumps(callback),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(DarajaCallbackEvent.objects.count(), 0)

    @override_settings(
        DARAJA_CONSUMER_KEY="sandbox-key",
        DARAJA_CONSUMER_SECRET="sandbox-secret",
        DARAJA_SHORTCODE="174379",
        DARAJA_PASSKEY="sandbox-passkey",
        DARAJA_CALLBACK_URL="https://example.invalid/api/payments/daraja/sandbox/stk/callback/",
        DARAJA_UNKNOWN_CALLBACKS_PER_MINUTE=1,
    )
    def test_unknown_callback_creation_is_rate_limited(self):
        url = reverse("daraja-stk-callback")
        for checkout_id in ("unknown-first", "unknown-second"):
            response = self.client.post(
                url,
                data=json.dumps(
                    {
                        "Body": {
                            "stkCallback": {
                                "CheckoutRequestID": checkout_id,
                                "ResultCode": 1,
                            }
                        }
                    }
                ),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
        self.assertEqual(DarajaCallbackEvent.objects.count(), 1)

    @override_settings(
        DARAJA_CONSUMER_KEY="sandbox-key",
        DARAJA_CONSUMER_SECRET="sandbox-secret",
        DARAJA_SHORTCODE="174379",
        DARAJA_PASSKEY="sandbox-passkey",
        DARAJA_CALLBACK_URL="https://example.invalid/api/payments/daraja/sandbox/stk/callback/",
        DARAJA_CALLBACK_REQUESTS_PER_IP=1,
        DARAJA_UNKNOWN_CALLBACKS_PER_MINUTE=10,
    )
    def test_callback_request_flood_is_rate_limited_by_client_ip(self):
        url = reverse("daraja-stk-callback")
        for checkout_id in ("callback-first", "callback-second"):
            response = self.client.post(
                url,
                data=json.dumps(
                    {
                        "Body": {
                            "stkCallback": {
                                "CheckoutRequestID": checkout_id,
                                "ResultCode": 1,
                            }
                        }
                    }
                ),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
        self.assertEqual(DarajaCallbackEvent.objects.count(), 1)

    @override_settings(
        DARAJA_CONSUMER_KEY="sandbox-key",
        DARAJA_CONSUMER_SECRET="sandbox-secret",
        DARAJA_SHORTCODE="174379",
        DARAJA_PASSKEY="sandbox-passkey",
        DARAJA_CALLBACK_URL="https://example.invalid/api/payments/daraja/sandbox/stk/callback/",
        DARAJA_CALLBACK_MAX_BODY_BYTES=16,
    )
    def test_oversized_callback_is_acknowledged_without_persistence(self):
        response = self.client.post(
            reverse("daraja-stk-callback"),
            data=json.dumps(
                {"Body": {"stkCallback": {"CheckoutRequestID": "too-large"}}}
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(DarajaCallbackEvent.objects.count(), 0)

    @override_settings(
        DARAJA_CONSUMER_KEY="sandbox-key",
        DARAJA_CONSUMER_SECRET="sandbox-secret",
        DARAJA_SHORTCODE="174379",
        DARAJA_PASSKEY="sandbox-passkey",
        DARAJA_CALLBACK_URL="https://example.invalid/api/payments/daraja/sandbox/stk/callback/",
    )
    @patch("invoicing.views.initiate_stk_push")
    @patch("invoicing.views.query_stk_push")
    def test_success_callback_requires_matching_query_ids_amount_and_phone(
        self, query, initiate
    ):
        initiate.return_value = {
            "ResponseCode": "0",
            "MerchantRequestID": "merchant-2",
            "CheckoutRequestID": "ws_CO_2",
        }
        query.return_value = {
            "ResponseCode": "0",
            "MerchantRequestID": "merchant-2",
            "CheckoutRequestID": "ws_CO_2",
            "ResultCode": "0",
            "ResultDesc": "The service request is processed successfully.",
        }
        url = reverse(
            "daraja-attempt-create", args=[self.organization.pk, self.invoice.pk]
        )
        created = self.post_json(
            url,
            {"amount": "5", "phone_number": "0700000000"},
            headers={"Idempotency-Key": str(uuid4())},
        )
        self.assertEqual(created.status_code, 202, created.content)
        callback_url = reverse("daraja-stk-callback")
        callback = {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "merchant-2",
                    "CheckoutRequestID": "ws_CO_2",
                    "ResultCode": 0,
                    "ResultDesc": "Success",
                    "CallbackMetadata": {
                        "Item": [
                            {"Name": "Amount", "Value": 5},
                            {"Name": "PhoneNumber", "Value": 254700000000},
                            {"Name": "MpesaReceiptNumber", "Value": "TEST123"},
                        ]
                    },
                }
            }
        }
        callback_response = self.client.post(
            callback_url,
            data=json.dumps(callback),
            content_type="application/json",
        )
        attempt = DarajaPaymentAttempt.objects.get(pk=created.json()["id"])
        self.assertEqual(callback_response.status_code, 200)
        self.assertEqual(attempt.status, DarajaPaymentAttempt.Status.SUCCEEDED)
        self.assertIsNone(attempt.payment_id)
        self.assertEqual(Payment.objects.count(), 0)
        event = DarajaCallbackEvent.objects.get(checkout_request_id="ws_CO_2")
        self.assertEqual(event.payload["CallbackMetadata"]["Item"][0]["Value"], 5)
        self.assertNotIn("254700000000", json.dumps(event.payload))
        self.assertNotIn("MpesaReceiptNumber", json.dumps(event.payload))

        self.client.post(
            callback_url,
            data=json.dumps(callback),
            content_type="application/json",
        )
        event.refresh_from_db()
        self.assertEqual(event.delivery_count, 2)
        self.assertEqual(query.call_count, 1)

    @override_settings(
        DARAJA_CONSUMER_KEY="sandbox-key",
        DARAJA_CONSUMER_SECRET="sandbox-secret",
        DARAJA_SHORTCODE="174379",
        DARAJA_PASSKEY="sandbox-passkey",
        DARAJA_CALLBACK_URL="https://example.invalid/api/payments/daraja/sandbox/stk/callback/",
    )
    @patch("invoicing.views.initiate_stk_push")
    @patch("invoicing.views.query_stk_push")
    def test_early_callback_is_attached_after_initiation_response(
        self, query, initiate
    ):
        query.return_value = {
            "ResponseCode": "0",
            "MerchantRequestID": "merchant-early",
            "CheckoutRequestID": "ws_CO_early",
            "ResultCode": "0",
            "ResultDesc": "Success",
        }
        callback = {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "merchant-early",
                    "CheckoutRequestID": "ws_CO_early",
                    "ResultCode": 0,
                    "CallbackMetadata": {
                        "Item": [
                            {"Name": "Amount", "Value": 5},
                            {"Name": "PhoneNumber", "Value": 254700000000},
                        ]
                    },
                }
            }
        }

        def initiate_with_early_callback(_attempt):
            self.client.post(
                reverse("daraja-stk-callback"),
                data=json.dumps(callback),
                content_type="application/json",
            )
            return {
                "ResponseCode": "0",
                "MerchantRequestID": "merchant-early",
                "CheckoutRequestID": "ws_CO_early",
            }

        initiate.side_effect = initiate_with_early_callback
        url = reverse(
            "daraja-attempt-create", args=[self.organization.pk, self.invoice.pk]
        )
        response = self.post_json(
            url,
            {"amount": "5", "phone_number": "0700000000"},
            headers={"Idempotency-Key": str(uuid4())},
        )
        attempt = DarajaPaymentAttempt.objects.get(pk=response.json()["id"])
        event = DarajaCallbackEvent.objects.get(checkout_request_id="ws_CO_early")
        self.assertEqual(event.attempt_id, attempt.pk)
        self.assertEqual(attempt.status, DarajaPaymentAttempt.Status.SUCCEEDED)
        self.assertEqual(query.call_count, 1)

    @override_settings(
        DARAJA_CONSUMER_KEY="sandbox-key",
        DARAJA_CONSUMER_SECRET="sandbox-secret",
        DARAJA_SHORTCODE="174379",
        DARAJA_PASSKEY="sandbox-passkey",
        DARAJA_CALLBACK_URL="https://example.invalid/api/payments/daraja/sandbox/stk/callback/",
    )
    @patch("invoicing.views.initiate_stk_push")
    @patch("invoicing.views.query_stk_push")
    def test_callback_mismatch_stays_in_review_and_can_be_reconciled(
        self, query, initiate
    ):
        initiate.return_value = {
            "ResponseCode": "0",
            "MerchantRequestID": "merchant-3",
            "CheckoutRequestID": "ws_CO_3",
        }
        query.side_effect = [
            TimeoutError("temporary"),
            {
                "ResponseCode": "0",
                "MerchantRequestID": "merchant-3",
                "CheckoutRequestID": "ws_CO_3",
                "ResultCode": "0",
                "ResultDesc": "Success",
            },
        ]
        url = reverse(
            "daraja-attempt-create", args=[self.organization.pk, self.invoice.pk]
        )
        created = self.post_json(
            url,
            {"amount": "5", "phone_number": "0700000000"},
            headers={"Idempotency-Key": str(uuid4())},
        )
        callback = {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "merchant-3",
                    "CheckoutRequestID": "ws_CO_3",
                    "ResultCode": 0,
                    "ResultDesc": "Success",
                    "CallbackMetadata": {
                        "Item": [
                            {"Name": "Amount", "Value": 99},
                            {"Name": "PhoneNumber", "Value": 254700000000},
                        ]
                    },
                }
            }
        }
        callback_url = reverse("daraja-stk-callback")
        self.client.post(
            callback_url,
            data=json.dumps(callback),
            content_type="application/json",
        )
        attempt = DarajaPaymentAttempt.objects.get(pk=created.json()["id"])
        self.assertEqual(attempt.status, DarajaPaymentAttempt.Status.PENDING)

        self.client.force_login(self.finance)
        reconcile_url = reverse(
            "daraja-attempt-reconcile", args=[self.organization.pk, attempt.pk]
        )
        reconciled = self.client.post(reconcile_url)
        attempt.refresh_from_db()
        self.assertEqual(reconciled.status_code, 202)
        self.assertEqual(attempt.status, DarajaPaymentAttempt.Status.REVIEW)
        self.assertEqual(Payment.objects.count(), 0)

    @override_settings(
        DARAJA_CONSUMER_KEY="sandbox-key",
        DARAJA_CONSUMER_SECRET="sandbox-secret",
        DARAJA_SHORTCODE="174379",
        DARAJA_PASSKEY="sandbox-passkey",
        DARAJA_CALLBACK_URL="https://example.invalid/api/payments/daraja/sandbox/stk/callback/",
    )
    @patch("invoicing.views.initiate_stk_push")
    @patch("invoicing.views.query_stk_push")
    def test_manual_receipt_links_to_confirmed_attempt_before_allocation(
        self, query, initiate
    ):
        initiate.side_effect = [
            {
                "ResponseCode": "0",
                "MerchantRequestID": "merchant-4",
                "CheckoutRequestID": "ws_CO_4",
            },
            {
                "ResponseCode": "0",
                "MerchantRequestID": "merchant-5",
                "CheckoutRequestID": "ws_CO_5",
            },
        ]
        query.return_value = {
            "ResponseCode": "0",
            "MerchantRequestID": "merchant-4",
            "CheckoutRequestID": "ws_CO_4",
            "ResultCode": "0",
            "ResultDesc": "Success",
        }
        attempt_url = reverse(
            "daraja-attempt-create", args=[self.organization.pk, self.invoice.pk]
        )
        started = self.post_json(
            attempt_url,
            {"amount": "5", "phone_number": "0700000000"},
            headers={"Idempotency-Key": str(uuid4())},
        )
        callback = {
            "Body": {
                "stkCallback": {
                    "MerchantRequestID": "merchant-4",
                    "CheckoutRequestID": "ws_CO_4",
                    "ResultCode": 0,
                    "CallbackMetadata": {
                        "Item": [
                            {"Name": "Amount", "Value": 5},
                            {"Name": "PhoneNumber", "Value": 254700000000},
                        ]
                    },
                }
            }
        }
        self.client.post(
            reverse("daraja-stk-callback"),
            data=json.dumps(callback),
            content_type="application/json",
        )
        attempt = DarajaPaymentAttempt.objects.get(pk=started.json()["id"])
        self.assertEqual(attempt.status, DarajaPaymentAttempt.Status.SUCCEEDED)
        self.assertIsNone(attempt.payment_id)

        payment_response, _, _ = self.record_payment(
            amount="5.00000", reference="ws_CO_4", method="mobile_money"
        )
        attempt.refresh_from_db()
        self.assertEqual(payment_response.status_code, 201, payment_response.content)
        self.assertEqual(str(attempt.payment_id), payment_response.json()["id"])
        allocation = self.allocate(attempt.payment_id, self.invoice.pk, "5.00000")
        self.assertEqual(allocation.status_code, 200, allocation.content)

        next_attempt = self.post_json(
            attempt_url,
            {"amount": "7", "phone_number": "0700000000"},
            headers={"Idempotency-Key": str(uuid4())},
        )
        self.assertEqual(next_attempt.status_code, 202, next_attempt.content)
        self.assertEqual(initiate.call_count, 2)
