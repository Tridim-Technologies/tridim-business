import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Membership, Organization
from quotations.models import Job, Quotation

from .models import Customer, CustomerStatusHistory


class CustomerLifecycleTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="customer-owner", password="a-long-test-password"
        )
        self.finance = user_model.objects.create_user(
            username="customer-finance", password="a-long-test-password"
        )
        self.outsider = user_model.objects.create_user(
            username="customer-outsider", password="a-long-test-password"
        )
        self.organization = Organization.objects.create(name="Customer Org")
        self.other_organization = Organization.objects.create(name="Other Org")
        Membership.objects.create(
            user=self.owner, organization=self.organization, role=Membership.Role.OWNER
        )
        Membership.objects.create(
            user=self.finance,
            organization=self.organization,
            role=Membership.Role.FINANCE,
        )
        self.customer = Customer.objects.create(
            organization=self.organization,
            name="Acme Service",
            email="ops@example.test",
            created_by=self.owner,
        )
        self.url = reverse("customers", args=[self.organization.pk])
        self.detail_url = reverse(
            "customer-detail", args=[self.organization.pk, self.customer.pk]
        )

    def test_directory_defaults_to_active_and_supports_filter_and_search(self):
        self.client.force_login(self.owner)
        self.assertEqual(
            [item["id"] for item in self.client.get(self.url).json()["results"]],
            [self.customer.pk],
        )
        self.customer.status = Customer.Status.ARCHIVED
        self.customer.save(update_fields=["status"])
        self.assertEqual(self.client.get(self.url).json()["results"], [])
        response = self.client.get(f"{self.url}?status=archived&search=example")
        self.assertEqual(
            [item["id"] for item in response.json()["results"]], [self.customer.pk]
        )
        self.assertEqual(self.client.get(f"{self.url}?status=invalid").status_code, 400)

    def test_archive_restore_is_audited_and_idempotent(self):
        self.client.force_login(self.owner)
        archived = self.client.post(
            self.detail_url,
            data=json.dumps({"action": "archive"}),
            content_type="application/json",
        )
        self.assertEqual(archived.status_code, 200)
        self.assertEqual(archived.json()["status"], Customer.Status.ARCHIVED)
        self.assertEqual(
            archived.json()["status_history"][0]["actor"], self.owner.username
        )
        self.client.post(
            self.detail_url,
            data=json.dumps({"action": "archive"}),
            content_type="application/json",
        )
        restored = self.client.post(
            self.detail_url,
            data=json.dumps({"action": "restore"}),
            content_type="application/json",
        )
        self.assertEqual(restored.json()["status"], Customer.Status.ACTIVE)
        self.assertEqual(
            list(
                CustomerStatusHistory.objects.filter(
                    customer=self.customer
                ).values_list("previous_status", "status", "actor_id")
            ),
            [
                (Customer.Status.ACTIVE, Customer.Status.ARCHIVED, self.owner.pk),
                (Customer.Status.ARCHIVED, Customer.Status.ACTIVE, self.owner.pk),
            ],
        )

    def test_only_customer_writers_can_change_lifecycle(self):
        self.client.force_login(self.finance)
        response = self.client.post(
            self.detail_url,
            data=json.dumps({"action": "archive"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.status, Customer.Status.ACTIVE)

    def test_customer_contact_details_can_be_updated_without_changing_lifecycle(self):
        self.client.force_login(self.owner)
        response = self.client.patch(
            self.detail_url,
            data=json.dumps(
                {
                    "name": "Acme Support",
                    "contact_name": "Morgan",
                    "email": "morgan@example.test",
                    "phone": "+1 555 0100",
                    "status": "archived",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.name, "Acme Support")
        self.assertEqual(self.customer.contact_name, "Morgan")
        self.assertEqual(self.customer.status, Customer.Status.ACTIVE)

    def test_customer_is_scoped_to_organization(self):
        self.client.force_login(self.owner)
        wrong_org_url = reverse(
            "customer-detail", args=[self.other_organization.pk, self.customer.pk]
        )
        response = self.client.post(
            wrong_org_url,
            data=json.dumps({"action": "archive"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_archiving_preserves_existing_quotation_and_job_links(self):
        quotation = Quotation.objects.create(
            organization=self.organization,
            customer=self.customer,
            currency="KES",
            valid_until="2026-10-12",
            created_by=self.owner,
            status=Quotation.Status.ACCEPTED,
        )
        job = Job.objects.create(
            organization=self.organization,
            customer=self.customer,
            source_quotation=quotation,
            created_by=self.owner,
        )
        self.client.force_login(self.owner)
        response = self.client.post(
            self.detail_url,
            data=json.dumps({"action": "archive"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        quotation.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(quotation.customer_id, self.customer.pk)
        self.assertEqual(job.customer_id, self.customer.pk)
