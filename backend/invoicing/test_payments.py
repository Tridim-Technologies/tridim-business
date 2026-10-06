import json
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization
from customers.models import Customer
from quotations.models import Job, Quotation, QuotationLine

from .models import Invoice, Payment, PaymentAllocation


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
