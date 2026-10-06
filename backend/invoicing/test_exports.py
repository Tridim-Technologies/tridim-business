import csv
import io
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization
from customers.models import Customer
from quotations.models import Job, Quotation

from .models import Invoice, Payment, PaymentAllocation


class FinanceExportTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="export-owner", password="a-long-test-password"
        )
        self.sales = user_model.objects.create_user(
            username="export-sales", password="a-long-test-password"
        )
        self.outsider = user_model.objects.create_user(
            username="export-outsider", password="a-long-test-password"
        )
        self.organization = Organization.objects.create(name="Export Org")
        self.other_organization = Organization.objects.create(name="Other Export Org")
        Membership.objects.create(
            user=self.owner,
            organization=self.organization,
            role=Membership.Role.OWNER,
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
        self.customer_name = '=HYPERLINK("https://example.test", "open")\ncontinued'
        self.customer = Customer.objects.create(
            organization=self.organization,
            name=self.customer_name,
            created_by=self.owner,
        )
        self.invoice = self.create_invoice(Decimal("12.34000"), Invoice.Status.ISSUED)
        self.payment = Payment.objects.create(
            organization=self.organization,
            customer=self.customer,
            customer_name=self.customer_name,
            received_date=timezone.localdate(),
            amount=Decimal("20.00000"),
            currency="KES",
            method=Payment.Method.BANK_TRANSFER,
            reference='=IMPORTXML("https://example.test")',
            recorded_by=self.owner,
        )
        self.active_allocation = PaymentAllocation.objects.create(
            payment=self.payment,
            invoice=self.invoice,
            amount=Decimal("3.00000"),
            allocated_by=self.owner,
        )
        self.reversed_allocation = PaymentAllocation.objects.create(
            payment=self.payment,
            invoice=self.invoice,
            amount=Decimal("2.00000"),
            allocated_by=self.owner,
            reversed_by=self.owner,
            reversed_at=timezone.now(),
            reversal_reason="Applied to the wrong amount",
        )
        self.unapplied_payment = Payment.objects.create(
            organization=self.organization,
            customer=self.customer,
            customer_name=self.customer_name,
            received_date=timezone.localdate(),
            amount=Decimal("5.00000"),
            currency="KES",
            method=Payment.Method.CASH,
            recorded_by=self.owner,
        )
        self.reversed_payment = Payment.objects.create(
            organization=self.organization,
            customer=self.customer,
            customer_name=self.customer_name,
            received_date=timezone.localdate(),
            amount=Decimal("7.00000"),
            currency="KES",
            method=Payment.Method.CASH,
            recorded_by=self.owner,
            reversed_by=self.owner,
            reversed_at=timezone.now(),
            reversal_reason="Receipt voided at source",
        )
        self.void_invoice = self.create_invoice(Decimal("4.50000"), Invoice.Status.VOID)

    def create_invoice(self, total, status):
        quotation = Quotation.objects.create(
            organization=self.organization,
            customer=self.customer,
            currency="KES",
            valid_until=timezone.localdate() + timedelta(days=14),
            created_by=self.owner,
            status=Quotation.Status.ACCEPTED,
        )
        job = Job.objects.create(
            organization=self.organization,
            customer=self.customer,
            source_quotation=quotation,
            status=Job.Status.COMPLETED,
            created_by=self.owner,
        )
        return Invoice.objects.create(
            organization=self.organization,
            job=job,
            source_quotation=quotation,
            customer=self.customer,
            customer_name=self.customer_name,
            invoice_number=f"EXP-{total}-{status}",
            status=status,
            issue_date=timezone.localdate(),
            due_date=timezone.localdate() + timedelta(days=30),
            currency="KES",
            total=total,
            issued_by=self.owner,
        )

    def get_export(self, resource, organization=None, user=None):
        self.client.force_login(user or self.owner)
        url = reverse(
            "finance-export", args=[organization or self.organization.pk, resource]
        )
        response = self.client.get(url)
        if response.status_code == 200:
            body = b"".join(response.streaming_content).decode("utf-8-sig")
            response.export_rows = list(csv.reader(io.StringIO(body)))
        return response

    @staticmethod
    def data_rows(response):
        headings = response.export_rows[2]
        return [
            dict(zip(headings, row, strict=True)) for row in response.export_rows[3:]
        ]

    def test_invoice_export_has_exact_current_balances_and_void_history(self):
        response = self.get_export("invoices")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response["Content-Disposition"].endswith('filename="invoices.csv"')
        )
        self.assertEqual(response.export_rows[0][0], "# export_as_of_utc")
        self.assertEqual(response.export_rows[2][0], "invoice_id")
        rows = {row["invoice_id"]: row for row in self.data_rows(response)}
        issued = rows[str(self.invoice.pk)]
        self.assertEqual(issued["issued_total"], "12.34000")
        self.assertEqual(issued["allocated_total"], "3.00000")
        self.assertEqual(issued["outstanding_total"], "9.34000")
        self.assertEqual(issued["payment_state"], "partial")
        self.assertEqual(issued["customer_name"], "'" + self.customer_name)
        voided = rows[str(self.void_invoice.pk)]
        self.assertEqual(voided["invoice_status"], "void")
        self.assertEqual(voided["outstanding_total"], "")
        self.assertEqual(voided["payment_state"], "void")
        self.assertEqual(response["X-Export-As-Of-UTC"], issued["export_as_of_utc"])

    def test_payment_export_keeps_unapplied_and_reversed_receipt_states(self):
        response = self.get_export("payments")
        rows = {row["payment_id"]: row for row in self.data_rows(response)}
        partial = rows[str(self.payment.pk)]
        self.assertEqual(partial["amount"], "20.00000")
        self.assertEqual(partial["allocated_total"], "3.00000")
        self.assertEqual(partial["unapplied_total"], "17.00000")
        self.assertEqual(partial["payment_state"], "partially_applied")
        self.assertTrue(partial["reference"].startswith("'=IMPORTXML"))
        unapplied = rows[str(self.unapplied_payment.pk)]
        self.assertEqual(unapplied["payment_state"], "unapplied")
        reversed_row = rows[str(self.reversed_payment.pk)]
        self.assertEqual(reversed_row["payment_state"], "reversed")
        self.assertEqual(reversed_row["unapplied_total"], "0.00000")
        self.assertEqual(reversed_row["reversal_reason"], "Receipt voided at source")

    def test_allocation_export_retains_reversed_allocations_and_escapes_csv(self):
        response = self.get_export("allocations")
        rows = {row["allocation_id"]: row for row in self.data_rows(response)}
        active = rows[str(self.active_allocation.pk)]
        self.assertEqual(active["allocation_state"], "active")
        self.assertEqual(active["amount"], "3.00000")
        reversed_row = rows[str(self.reversed_allocation.pk)]
        self.assertEqual(reversed_row["allocation_state"], "reversed")
        self.assertEqual(reversed_row["reversal_reason"], "Applied to the wrong amount")
        self.assertEqual(reversed_row["customer_name"], "'" + self.customer_name)
        self.assertEqual(reversed_row["payment_state"], "active")

    def test_exports_are_finance_role_and_organization_scoped(self):
        self.assertEqual(self.get_export("invoices", user=self.sales).status_code, 403)
        self.assertEqual(
            self.get_export(
                "invoices", organization=self.other_organization.pk, user=self.owner
            ).status_code,
            404,
        )
        self.assertEqual(self.get_export("not-a-resource").status_code, 404)
