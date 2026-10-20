import json
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Membership, Organization
from customers.models import Customer
from quotations.models import Job, Quotation

from .models import JobMaterialIssue, Location, Product, StockMovement


class JobMaterialIssueTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="material-owner")
        self.operations = user_model.objects.create_user(username="material-ops")
        self.finance = user_model.objects.create_user(username="material-finance")
        self.other_owner = user_model.objects.create_user(username="material-other")
        self.organization = Organization.objects.create(name="Material Org")
        self.other_organization = Organization.objects.create(name="Other Material Org")
        for user, role in (
            (self.owner, Membership.Role.OWNER),
            (self.operations, Membership.Role.OPERATIONS),
            (self.finance, Membership.Role.FINANCE),
        ):
            Membership.objects.create(
                user=user, organization=self.organization, role=role
            )
        Membership.objects.create(
            user=self.other_owner,
            organization=self.other_organization,
            role=Membership.Role.OWNER,
        )
        customer = Customer.objects.create(
            organization=self.organization,
            name="Material Customer",
            created_by=self.owner,
        )
        quotation = Quotation.objects.create(
            organization=self.organization,
            customer=customer,
            currency="KES",
            valid_until=date.today() + timedelta(days=7),
            created_by=self.owner,
            status=Quotation.Status.ACCEPTED,
        )
        self.job = Job.objects.create(
            organization=self.organization,
            customer=customer,
            source_quotation=quotation,
            created_by=self.owner,
        )
        self.product = Product.objects.create(
            organization=self.organization,
            sku="MAT-01",
            name="Cable",
            base_unit="m",
            created_by=self.owner,
        )
        self.product_two = Product.objects.create(
            organization=self.organization,
            sku="MAT-02",
            name="Fastener",
            base_unit="ea",
            created_by=self.owner,
        )
        self.location = Location.objects.create(
            organization=self.organization,
            code="STORE",
            name="Main store",
            created_by=self.owner,
        )
        self.other_product = Product.objects.create(
            organization=self.other_organization,
            sku="OTHER",
            name="Other item",
            base_unit="ea",
            created_by=self.other_owner,
        )
        self.issue_url = reverse(
            "job-material-issues", args=[self.organization.pk, self.job.pk]
        )
        self.list_url = reverse("jobs", args=[self.organization.pk])
        self.inventory_url = reverse("inventory", args=[self.organization.pk])
        self.client.force_login(self.operations)
        self.receive(self.product, "8.000")
        self.receive(self.product_two, "1.000")

    def receive(self, product, quantity):
        StockMovement.objects.create(
            organization=self.organization,
            product=product,
            kind=StockMovement.Kind.RECEIPT,
            location=self.location,
            quantity=Decimal(quantity),
            reason="Synthetic opening stock",
            idempotency_key=uuid.uuid4(),
            actor=self.owner,
        )

    def post_issue(self, payload, *, user=None):
        if user:
            self.client.force_login(user)
        return self.client.post(
            self.issue_url, data=json.dumps(payload), content_type="application/json"
        )

    def payload(self, *, key=None, lines=None, reason="Used during installation"):
        return {
            "idempotency_key": str(key or uuid.uuid4()),
            "reason": reason,
            "lines": lines
            or [
                {
                    "product_id": self.product.pk,
                    "location_id": self.location.pk,
                    "quantity": "2.500",
                }
            ],
        }

    def test_issue_is_atomic_audited_linked_and_idempotent(self):
        payload = self.payload(
            lines=[
                {
                    "product_id": self.product.pk,
                    "location_id": self.location.pk,
                    "quantity": "2.500",
                },
                {
                    "product_id": self.product_two.pk,
                    "location_id": self.location.pk,
                    "quantity": "1.000",
                },
            ]
        )
        response = self.post_issue(payload)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertFalse(response.json()["replayed"])
        self.assertEqual(len(response.json()["lines"]), 2)
        issue = JobMaterialIssue.objects.get()
        self.assertEqual(issue.actor, self.operations)
        movements = StockMovement.objects.filter(
            source_job_material_issue_line__issue=issue
        )
        self.assertEqual(movements.count(), 2)
        self.assertTrue(
            all(movement.kind == StockMovement.Kind.ISSUE for movement in movements)
        )

        replay = self.post_issue(payload)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()["replayed"])
        self.assertEqual(movements.count(), 2)
        conflict = self.post_issue({**payload, "reason": "Different work"})
        self.assertEqual(conflict.status_code, 409)

        job = self.client.get(self.list_url).json()["results"][0]
        self.assertEqual(job["material_issues"][0]["id"], issue.pk)
        inventory = self.client.get(self.inventory_url).json()
        linked = next(
            item for item in inventory["movements"] if item["job_id"] == self.job.pk
        )
        self.assertEqual(
            linked["reason"], f"Job #{self.job.pk}: Used during installation"
        )

    def test_insufficient_stock_and_foreign_objects_leave_no_partial_issue(self):
        payload = self.payload(
            lines=[
                {
                    "product_id": self.product.pk,
                    "location_id": self.location.pk,
                    "quantity": "2.000",
                },
                {
                    "product_id": self.product_two.pk,
                    "location_id": self.location.pk,
                    "quantity": "2.000",
                },
            ]
        )
        response = self.post_issue(payload)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(JobMaterialIssue.objects.count(), 0)
        self.assertEqual(
            StockMovement.objects.filter(
                source_job_material_issue_line__isnull=False
            ).count(),
            0,
        )

        foreign = self.post_issue(
            self.payload(
                lines=[
                    {
                        "product_id": self.other_product.pk,
                        "location_id": self.location.pk,
                        "quantity": "1.000",
                    }
                ]
            )
        )
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(JobMaterialIssue.objects.count(), 0)

    def test_manager_role_is_required_and_quantity_must_be_exact_decimal(self):
        denied = self.post_issue(self.payload(), user=self.finance)
        self.assertEqual(denied.status_code, 403)
        floating = self.post_issue(
            self.payload(
                lines=[
                    {
                        "product_id": self.product.pk,
                        "location_id": self.location.pk,
                        "quantity": 1.25,
                    }
                ]
            ),
            user=self.operations,
        )
        self.assertEqual(floating.status_code, 400)
        self.assertEqual(JobMaterialIssue.objects.count(), 0)
