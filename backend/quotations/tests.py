from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization
from customers.models import Customer

from .models import Job, Quotation, QuotationStatusHistory


class QuotationWorkflowTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="owner", password="a-long-test-password"
        )
        self.sales = user_model.objects.create_user(
            username="sales", password="a-long-test-password"
        )
        self.operations = user_model.objects.create_user(
            username="operations", password="a-long-test-password"
        )
        self.finance = user_model.objects.create_user(
            username="finance", password="a-long-test-password"
        )
        self.outsider = user_model.objects.create_user(
            username="outsider", password="a-long-test-password"
        )
        self.organization = Organization.objects.create(name="Alpha Services")
        self.other_organization = Organization.objects.create(name="Other Services")
        for user, role in (
            (self.owner, Membership.Role.OWNER),
            (self.sales, Membership.Role.SALES),
            (self.operations, Membership.Role.OPERATIONS),
            (self.finance, Membership.Role.FINANCE),
        ):
            Membership.objects.create(
                user=user, organization=self.organization, role=role
            )
        self.customer = Customer.objects.create(
            organization=self.organization,
            name="Synthetic Customer",
            created_by=self.owner,
        )
        self.other_customer = Customer.objects.create(
            organization=self.other_organization,
            name="Other Customer",
            created_by=self.owner,
        )
        self.list_url = reverse("quotations", args=[self.organization.pk])
        self.payload = {
            "customer_id": self.customer.pk,
            "currency": "kes",
            "valid_until": (timezone.localdate() + timedelta(days=7)).isoformat(),
            "lines": [
                {
                    "description": "Synthetic service",
                    "quantity": "2.500",
                    "unit_price": "125.00",
                }
            ],
        }

    def create_quotation(self):
        self.client.force_login(self.sales)
        response = self.client.post(
            self.list_url, self.payload, content_type="application/json"
        )
        self.assertEqual(response.status_code, 201, response.content)
        return Quotation.objects.get(pk=response.json()["id"])

    def transition(self, quotation, action, user=None):
        self.client.force_login(user or self.owner)
        return self.client.post(
            reverse(
                "quotation-transition",
                args=[self.organization.pk, quotation.pk],
            ),
            {"action": action},
            content_type="application/json",
        )

    def test_sales_can_create_decimal_quotation_with_creation_history(self):
        quotation = self.create_quotation()
        self.assertEqual(quotation.currency, "KES")
        self.assertEqual(quotation.lines.get().quantity, Decimal("2.500"))
        self.assertEqual(quotation.lines.get().unit_price, Decimal("125.00"))
        history = quotation.status_history.get()
        self.assertEqual(history.status, Quotation.Status.DRAFT)
        self.assertEqual(history.actor, self.sales)

    def test_quotation_customer_must_belong_to_organization(self):
        self.client.force_login(self.sales)
        response = self.client.post(
            self.list_url,
            {**self.payload, "customer_id": self.other_customer.pk},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("customer_id", response.json())

    def test_empty_lines_are_rejected(self):
        self.client.force_login(self.sales)
        response = self.client.post(
            self.list_url,
            {**self.payload, "lines": []},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Quotation.objects.exists())

    def test_finance_cannot_create_quote_or_accept_work(self):
        self.client.force_login(self.finance)
        response = self.client.post(
            self.list_url, self.payload, content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)
        quotation = self.create_quotation()
        self.transition(quotation, "send")
        self.assertEqual(
            self.transition(quotation, "accept", self.finance).status_code, 403
        )

    def test_non_member_cannot_list_or_probe_quote(self):
        quotation = self.create_quotation()
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.list_url).status_code, 404)
        detail = reverse("quotation-detail", args=[self.organization.pk, quotation.pk])
        self.assertEqual(self.client.get(detail).status_code, 404)

    def test_quote_and_job_are_tenant_scoped_on_read(self):
        quotation = self.create_quotation()
        self.client.force_login(self.owner)
        wrong_org_url = reverse(
            "quotation-detail", args=[self.other_organization.pk, quotation.pk]
        )
        self.assertEqual(self.client.get(wrong_org_url).status_code, 404)

    def test_acceptance_records_history_and_creates_one_linked_job_on_retry(self):
        quotation = self.create_quotation()
        self.assertEqual(self.transition(quotation, "send").status_code, 200)
        accepted = self.transition(quotation, "accept", self.operations)
        self.assertEqual(accepted.status_code, 200, accepted.content)
        job_id = accepted.json()["job_id"]
        retried = self.transition(quotation, "accept", self.operations)
        self.assertEqual(retried.status_code, 200, retried.content)
        self.assertEqual(retried.json()["job_id"], job_id)
        job = Job.objects.get(source_quotation=quotation)
        self.assertEqual(job.organization, self.organization)
        self.assertEqual(job.customer, self.customer)
        self.assertEqual(job.created_by, self.operations)
        self.assertEqual(Job.objects.count(), 1)
        self.assertEqual(
            list(quotation.status_history.values_list("status", flat=True)),
            ["draft", "sent", "accepted"],
        )
        self.assertEqual(
            quotation.status_history.get(status="accepted").actor, self.operations
        )

    def test_invalid_transition_is_rejected_without_a_job(self):
        quotation = self.create_quotation()
        response = self.transition(quotation, "accept", self.operations)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Job.objects.exists())
        self.assertEqual(QuotationStatusHistory.objects.count(), 1)

    def test_sales_user_cannot_accept_a_sent_quotation(self):
        quotation = self.create_quotation()
        self.transition(quotation, "send")
        response = self.transition(quotation, "accept", self.sales)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(quotation.status_history.count(), 2)
        self.assertFalse(Job.objects.exists())

    def test_expired_draft_cannot_be_sent(self):
        quotation = self.create_quotation()
        quotation.valid_until = timezone.localdate() - timedelta(days=1)
        quotation.save(update_fields=["valid_until"])
        response = self.transition(quotation, "send")
        self.assertEqual(response.status_code, 409)
        quotation.refresh_from_db()
        self.assertEqual(quotation.status, Quotation.Status.EXPIRED)
        self.assertEqual(quotation.status_history.count(), 2)

    def test_rejection_is_distinct_and_terminal(self):
        quotation = self.create_quotation()
        self.transition(quotation, "send")
        rejected = self.transition(quotation, "reject")
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json()["status"], Quotation.Status.REJECTED)
        self.assertEqual(
            self.transition(quotation, "accept", self.operations).status_code, 409
        )
        self.assertFalse(Job.objects.exists())

    def test_acceptance_after_validity_date_marks_quote_expired(self):
        quotation = self.create_quotation()
        self.transition(quotation, "send")
        quotation.valid_until = timezone.localdate() - timedelta(days=1)
        quotation.save(update_fields=["valid_until"])
        response = self.transition(quotation, "accept", self.operations)
        self.assertEqual(response.status_code, 409)
        quotation.refresh_from_db()
        self.assertEqual(quotation.status, Quotation.Status.EXPIRED)
        self.assertTrue(quotation.status_history.filter(status="expired").exists())
        self.assertFalse(Job.objects.exists())

    def test_unauthenticated_user_cannot_list_quotations(self):
        self.assertEqual(self.client.get(self.list_url).status_code, 401)
