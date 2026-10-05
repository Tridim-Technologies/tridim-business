import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization
from customers.models import Customer
from quotations.models import Job, Quotation, QuotationLine

from .models import Invoice, InvoiceLine, InvoiceSequence


class InvoiceWorkflowTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="invoice-owner", password="a-long-test-password"
        )
        self.finance = user_model.objects.create_user(
            username="invoice-finance", password="a-long-test-password"
        )
        self.sales = user_model.objects.create_user(
            username="invoice-sales", password="a-long-test-password"
        )
        self.employee = user_model.objects.create_user(
            username="invoice-employee", password="a-long-test-password"
        )
        self.outsider = user_model.objects.create_user(
            username="invoice-outsider", password="a-long-test-password"
        )
        self.organization = Organization.objects.create(name="Invoice Org")
        self.other_organization = Organization.objects.create(name="Other Invoice Org")
        for user, role in (
            (self.owner, Membership.Role.OWNER),
            (self.finance, Membership.Role.FINANCE),
            (self.sales, Membership.Role.SALES),
            (self.employee, Membership.Role.EMPLOYEE),
        ):
            Membership.objects.create(
                user=user, organization=self.organization, role=role
            )
        self.other_membership = Membership.objects.create(
            user=self.outsider,
            organization=self.other_organization,
            role=Membership.Role.FINANCE,
        )
        self.customer = Customer.objects.create(
            organization=self.organization,
            name="Invoice Customer",
            created_by=self.owner,
        )
        self.quotation = Quotation.objects.create(
            organization=self.organization,
            customer=self.customer,
            currency="KES",
            valid_until=timezone.localdate() + timedelta(days=14),
            created_by=self.owner,
            status=Quotation.Status.ACCEPTED,
        )
        QuotationLine.objects.create(
            quotation=self.quotation,
            description="Installation",
            quantity=Decimal("1.125"),
            unit_price=Decimal("10.10"),
            position=0,
        )
        QuotationLine.objects.create(
            quotation=self.quotation,
            description="Setup",
            quantity=Decimal("2.000"),
            unit_price=Decimal("0.33"),
            position=1,
        )
        self.job = Job.objects.create(
            organization=self.organization,
            customer=self.customer,
            source_quotation=self.quotation,
            status=Job.Status.COMPLETED,
            created_by=self.owner,
        )
        self.issue_url = reverse(
            "invoice-issue", args=[self.organization.pk, self.job.pk]
        )
        self.list_url = reverse("invoices", args=[self.organization.pk])

    def post_json(self, url, payload, user=None):
        self.client.force_login(user or self.finance)
        return self.client.post(
            url, data=json.dumps(payload), content_type="application/json"
        )

    def issue_invoice(self, due_date=None, user=None, extra=None):
        payload = {
            "due_date": due_date
            or (timezone.localdate() + timedelta(days=30)).isoformat()
        }
        if extra:
            payload.update(extra)
        return self.post_json(self.issue_url, payload, user=user)

    def test_invoice_snapshots_quote_lines_and_exact_decimal_totals(self):
        attempted_override = self.issue_invoice(
            extra={
                "correction_reason": "Change source amount",
                "lines": [
                    {"position": 0, "quantity": "1.125", "unit_price": "10.20"},
                    {"position": 1, "quantity": "2.000", "unit_price": "0.33"},
                ],
            }
        )
        self.assertEqual(attempted_override.status_code, 400)
        self.assertFalse(Invoice.objects.exists())
        response = self.issue_invoice()
        self.assertEqual(response.status_code, 201, response.content)
        invoice = Invoice.objects.get()
        self.assertEqual(
            invoice.invoice_number, f"INV-{timezone.localdate().year}-000001"
        )
        self.assertEqual(invoice.total, Decimal("12.02250"))
        self.assertEqual(invoice.currency, "KES")
        self.assertEqual(invoice.source_quotation, self.quotation)
        self.assertEqual(invoice.customer, self.customer)
        self.assertEqual(invoice.customer_name, "Invoice Customer")
        self.assertEqual(invoice.issued_by, self.finance)
        self.assertEqual(
            list(invoice.lines.values_list("line_total", flat=True)),
            [Decimal("11.36250"), Decimal("0.66000")],
        )
        self.assertEqual(response.json()["total"], "12.02250")
        self.customer.name = "Renamed after issue"
        self.customer.save(update_fields=["name"])
        invoice.refresh_from_db()
        self.assertEqual(invoice.customer_name, "Invoice Customer")

    def test_only_completed_jobs_can_be_invoiced(self):
        self.job.status = Job.Status.IN_PROGRESS
        self.job.save(update_fields=["status"])
        response = self.issue_invoice()
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Invoice.objects.exists())
        self.assertFalse(InvoiceSequence.objects.exists())

    def test_repeated_issue_returns_the_existing_invoice(self):
        first = self.issue_invoice()
        repeated = self.issue_invoice(timezone.localdate().isoformat())
        self.assertEqual(first.status_code, 201)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json()["id"], first.json()["id"])
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(InvoiceSequence.objects.get().next_number, 2)

    def test_void_requires_a_reason_and_reissue_keeps_both_records(self):
        issued = self.issue_invoice().json()
        void_url = reverse("invoice-void", args=[self.organization.pk, issued["id"]])
        missing_reason = self.post_json(void_url, {"reason": "  "})
        self.assertEqual(missing_reason.status_code, 400)
        voided = self.post_json(void_url, {"reason": "Corrected customer reference"})
        self.assertEqual(voided.status_code, 200, voided.content)
        first_invoice = Invoice.objects.get(pk=issued["id"])
        self.assertEqual(first_invoice.status, Invoice.Status.VOID)
        self.assertEqual(first_invoice.void_reason, "Corrected customer reference")
        self.assertEqual(first_invoice.voided_by, self.finance)
        self.assertIsNotNone(first_invoice.voided_at)

        missing_correction = self.issue_invoice()
        self.assertEqual(missing_correction.status_code, 400)
        incomplete_replacement = self.issue_invoice(
            extra={
                "correction_reason": "Corrected approved unit rate",
                "lines": [{"position": 0, "quantity": "1.125", "unit_price": "10.20"}],
            }
        )
        self.assertEqual(incomplete_replacement.status_code, 400)
        self.assertEqual(InvoiceSequence.objects.get().next_number, 2)
        replacement_response = self.issue_invoice(
            extra={
                "correction_reason": "Corrected approved unit rate",
                "lines": [
                    {"position": 0, "quantity": "1.125", "unit_price": "10.20"},
                    {"position": 1, "quantity": "2.000", "unit_price": "0.33"},
                ],
            }
        )
        self.assertEqual(replacement_response.status_code, 201)
        replacement = Invoice.objects.get(pk=replacement_response.json()["id"])
        self.assertEqual(
            replacement.invoice_number, f"INV-{timezone.localdate().year}-000002"
        )
        self.assertEqual(replacement.replaces, first_invoice)
        self.assertEqual(replacement.correction_reason, "Corrected approved unit rate")
        self.assertEqual(replacement.total, Decimal("12.13500"))
        self.assertEqual(Invoice.objects.count(), 2)
        self.assertEqual(InvoiceLine.objects.count(), 4)
        first_line = InvoiceLine.objects.filter(invoice=first_invoice).get(position=0)
        self.assertEqual(first_line.unit_price, Decimal("10.10"))

    def test_invoice_register_requires_finance_access_and_is_tenant_scoped(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.list_url).status_code, 200)
        self.issue_invoice()
        self.client.force_login(self.finance)
        self.assertEqual(len(self.client.get(self.list_url).json()["results"]), 1)
        self.client.force_login(self.sales)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.client.force_login(self.outsider)
        wrong_org_url = reverse("invoices", args=[self.other_organization.pk])
        self.assertEqual(self.client.get(wrong_org_url).status_code, 200)
        self.assertEqual(self.client.get(self.list_url).status_code, 404)
        wrong_job_url = reverse(
            "invoice-issue", args=[self.other_organization.pk, self.job.pk]
        )
        self.assertEqual(
            self.client.post(
                wrong_job_url,
                data=json.dumps({"due_date": timezone.localdate().isoformat()}),
                content_type="application/json",
            ).status_code,
            404,
        )

    def test_invoice_numbering_is_independent_per_organization_and_year(self):
        first = self.issue_invoice()
        sequence = InvoiceSequence.objects.get(organization=self.organization)
        self.assertEqual(sequence.year, timezone.localdate().year)
        self.assertEqual(sequence.next_number, 2)

        other_customer = Customer.objects.create(
            organization=self.other_organization,
            name="Other invoice customer",
            created_by=self.outsider,
        )
        other_quotation = Quotation.objects.create(
            organization=self.other_organization,
            customer=other_customer,
            currency="USD",
            valid_until=timezone.localdate() + timedelta(days=14),
            created_by=self.outsider,
            status=Quotation.Status.ACCEPTED,
        )
        QuotationLine.objects.create(
            quotation=other_quotation,
            description="Consulting",
            quantity=Decimal("1.000"),
            unit_price=Decimal("9.99"),
            position=0,
        )
        other_job = Job.objects.create(
            organization=self.other_organization,
            customer=other_customer,
            source_quotation=other_quotation,
            status=Job.Status.COMPLETED,
            created_by=self.outsider,
        )
        other_issue_url = reverse(
            "invoice-issue", args=[self.other_organization.pk, other_job.pk]
        )
        second = self.post_json(
            other_issue_url,
            {"due_date": (timezone.localdate() + timedelta(days=30)).isoformat()},
            user=self.outsider,
        )
        self.assertEqual(second.status_code, 201, second.content)
        self.assertEqual(
            second.json()["invoice_number"], first.json()["invoice_number"]
        )
        self.assertEqual(
            InvoiceSequence.objects.get(
                organization=self.other_organization
            ).next_number,
            2,
        )
