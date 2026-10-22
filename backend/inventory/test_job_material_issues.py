import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from accounts.models import Membership, Organization
from customers.models import Customer
from quotations.models import Job, Quotation

from .models import (
    JobMaterialIssue,
    JobMaterialReservation,
    Location,
    Product,
    StockMovement,
)


class JobMaterialIssueTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="material-owner")
        self.admin = user_model.objects.create_user(username="material-admin")
        self.operations = user_model.objects.create_user(username="material-ops")
        self.sales = user_model.objects.create_user(username="material-sales")
        self.finance = user_model.objects.create_user(username="material-finance")
        self.employee = user_model.objects.create_user(username="material-employee")
        self.other_owner = user_model.objects.create_user(username="material-other")
        self.organization = Organization.objects.create(name="Material Org")
        self.other_organization = Organization.objects.create(name="Other Material Org")
        for user, role in (
            (self.owner, Membership.Role.OWNER),
            (self.admin, Membership.Role.ADMIN),
            (self.operations, Membership.Role.OPERATIONS),
            (self.sales, Membership.Role.SALES),
            (self.finance, Membership.Role.FINANCE),
            (self.employee, Membership.Role.EMPLOYEE),
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
        self.reservation_url = reverse(
            "job-material-reservations", args=[self.organization.pk, self.job.pk]
        )
        self.movement_url = reverse("inventory-movements", args=[self.organization.pk])
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

    def post_reservation(self, payload, *, user=None):
        if user:
            self.client.force_login(user)
        return self.client.post(
            self.reservation_url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def reservation_payload(self, *, key=None, quantity="5.000", product=None):
        return {
            "idempotency_key": str(key or uuid.uuid4()),
            "reason": "Materials planned for installation",
            "lines": [
                {
                    "product_id": (product or self.product).pk,
                    "location_id": self.location.pk,
                    "quantity": quantity,
                }
            ],
        }

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

    def test_job_material_issue_write_role_matrix(self):
        for user in (self.owner, self.admin, self.operations):
            role = Membership.objects.get(
                user=user, organization=self.organization
            ).role
            with self.subTest(allowed_role=role):
                response = self.post_issue(
                    self.payload(
                        lines=[
                            {
                                "product_id": self.product.pk,
                                "location_id": self.location.pk,
                                "quantity": "0.500",
                            }
                        ]
                    ),
                    user=user,
                )
                self.assertEqual(response.status_code, 201, response.content)
                self.assertEqual(response.json()["actor"], user.username)

        issue_count = JobMaterialIssue.objects.count()
        movement_count = StockMovement.objects.filter(
            source_job_material_issue_line__isnull=False
        ).count()
        for user in (self.sales, self.finance, self.employee):
            role = Membership.objects.get(
                user=user, organization=self.organization
            ).role
            with self.subTest(denied_role=role):
                response = self.post_issue(self.payload(), user=user)
                self.assertEqual(response.status_code, 403, response.content)
                self.assertEqual(JobMaterialIssue.objects.count(), issue_count)
                self.assertEqual(
                    StockMovement.objects.filter(
                        source_job_material_issue_line__isnull=False
                    ).count(),
                    movement_count,
                )

    def test_reservations_reduce_available_stock_and_allow_partial_consumption(self):
        payload = self.reservation_payload()
        response = self.post_reservation(payload)
        self.assertEqual(response.status_code, 201, response.content)
        reservation = JobMaterialReservation.objects.get()
        self.assertEqual(response.json()["status"], "active")
        self.assertEqual(response.json()["lines"][0]["remaining_quantity"], "5.000")

        replay = self.post_reservation(payload)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()["replayed"])
        self.assertEqual(JobMaterialReservation.objects.count(), 1)

        inventory_product = next(
            item
            for item in self.client.get(self.inventory_url).json()["products"]
            if item["id"] == self.product.pk
        )
        balance = inventory_product["balances"][0]
        self.assertEqual(balance["quantity"], "8.000")
        self.assertEqual(balance["reserved_quantity"], "5.000")
        self.assertEqual(balance["available_quantity"], "3.000")

        generic_issue = self.client.post(
            self.movement_url,
            data=json.dumps(
                {
                    "product_id": self.product.pk,
                    "location_id": self.location.pk,
                    "kind": "issue",
                    "quantity": "4.000",
                    "reason": "Try to consume reserved stock",
                    "idempotency_key": str(uuid.uuid4()),
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(generic_issue.status_code, 409)
        second_location = Location.objects.create(
            organization=self.organization,
            code="SECOND",
            name="Second store",
            created_by=self.owner,
        )
        for movement in (
            {
                "kind": "adjustment",
                "direction": "decrease",
                "quantity": "4.000",
            },
            {
                "kind": "transfer",
                "destination_id": second_location.pk,
                "quantity": "4.000",
            },
        ):
            blocked = self.client.post(
                self.movement_url,
                data=json.dumps(
                    {
                        "product_id": self.product.pk,
                        "location_id": self.location.pk,
                        "reason": "Try to consume reserved stock",
                        "idempotency_key": str(uuid.uuid4()),
                        **movement,
                    }
                ),
                content_type="application/json",
            )
            self.assertEqual(blocked.status_code, 409)

        reservation_line_id = response.json()["lines"][0]["id"]
        issue_payload = self.payload(
            lines=[
                {
                    "product_id": self.product.pk,
                    "location_id": self.location.pk,
                    "reservation_line_id": reservation_line_id,
                    "quantity": "2.000",
                }
            ]
        )
        issue_response = self.post_issue(issue_payload)
        self.assertEqual(issue_response.status_code, 201, issue_response.content)
        self.assertEqual(
            issue_response.json()["lines"][0]["reservation_line_id"],
            reservation_line_id,
        )
        self.assertEqual(self.post_issue(issue_payload).json()["replayed"], True)

        job_reservations = self.client.get(self.reservation_url).json()["results"]
        self.assertEqual(job_reservations[0]["lines"][0]["issued_quantity"], "2.000")
        self.assertEqual(job_reservations[0]["lines"][0]["remaining_quantity"], "3.000")

        available_issue = self.client.post(
            self.movement_url,
            data=json.dumps(
                {
                    "product_id": self.product.pk,
                    "location_id": self.location.pk,
                    "kind": "issue",
                    "quantity": "3.000",
                    "reason": "Use unreserved stock",
                    "idempotency_key": str(uuid.uuid4()),
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(available_issue.status_code, 201, available_issue.content)

        direct_issue = self.post_issue(
            self.payload(
                lines=[
                    {
                        "product_id": self.product.pk,
                        "location_id": self.location.pk,
                        "quantity": "4.000",
                    }
                ]
            )
        )
        self.assertEqual(direct_issue.status_code, 409)

        release_url = reverse(
            "job-material-reservation-release",
            args=[self.organization.pk, self.job.pk, reservation.pk],
        )
        released = self.client.post(
            release_url, data="{}", content_type="application/json"
        )
        self.assertEqual(released.status_code, 200)
        self.assertEqual(released.json()["status"], "released")
        release_replay = self.client.post(
            release_url, data="{}", content_type="application/json"
        )
        self.assertTrue(release_replay.json()["replayed"])


@skipUnless(
    connection.features.has_select_for_update,
    "The configured test database does not support row-level locking.",
)
class InventoryReservationConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="reservation-lock-owner")
        self.operations = user_model.objects.create_user(
            username="reservation-lock-ops"
        )
        self.organization = Organization.objects.create(name="Reservation Lock Org")
        for user, role in (
            (self.owner, Membership.Role.OWNER),
            (self.operations, Membership.Role.OPERATIONS),
        ):
            Membership.objects.create(
                organization=self.organization, user=user, role=role
            )
        customer = Customer.objects.create(
            organization=self.organization,
            name="Reservation Lock Customer",
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
            sku="RES-LOCK-1",
            name="Reservation Lock Item",
            base_unit="ea",
            created_by=self.owner,
        )
        self.location = Location.objects.create(
            organization=self.organization,
            code="RES-LOCK",
            name="Reservation Lock Location",
            created_by=self.owner,
        )
        StockMovement.objects.create(
            organization=self.organization,
            product=self.product,
            kind=StockMovement.Kind.RECEIPT,
            location=self.location,
            quantity=Decimal("1.000"),
            reason="Synthetic concurrency-test opening stock",
            idempotency_key=uuid.uuid4(),
            actor=self.owner,
        )
        self.url = reverse(
            "job-material-reservations", args=[self.organization.pk, self.job.pk]
        )

    def test_concurrent_reservations_cannot_double_allocate_stock(self):
        barrier = Barrier(2)

        def reserve(user):
            close_old_connections()
            try:
                client = self.client_class()
                client.force_login(user)
                barrier.wait(timeout=10)
                response = client.post(
                    self.url,
                    data=json.dumps(
                        {
                            "idempotency_key": str(uuid.uuid4()),
                            "reason": "Concurrent planned work",
                            "lines": [
                                {
                                    "product_id": self.product.pk,
                                    "location_id": self.location.pk,
                                    "quantity": "0.750",
                                }
                            ],
                        }
                    ),
                    content_type="application/json",
                )
                return response.status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(reserve, user) for user in (self.owner, self.operations)
            ]
            statuses = sorted(future.result(timeout=30) for future in futures)
        self.assertEqual(statuses, [201, 409])
        self.assertEqual(
            JobMaterialReservation.objects.filter(
                organization=self.organization,
                status=JobMaterialReservation.Status.ACTIVE,
            ).count(),
            1,
        )

    def test_reservations_reject_overcommit_float_and_foreign_objects(self):
        self.assertEqual(
            self.post_reservation(
                self.reservation_payload(quantity="8.001")
            ).status_code,
            409,
        )
        floating = self.reservation_payload()
        floating["lines"][0]["quantity"] = 2.5
        self.assertEqual(self.post_reservation(floating).status_code, 400)
        foreign = self.reservation_payload(product=self.other_product)
        self.assertEqual(self.post_reservation(foreign).status_code, 404)
        self.assertEqual(JobMaterialReservation.objects.count(), 0)

    def test_reservation_read_and_write_permissions_are_scoped(self):
        self.assertEqual(
            self.post_reservation(
                self.reservation_payload(), user=self.finance
            ).status_code,
            403,
        )
        denied_read = self.client.get(self.reservation_url)
        self.assertEqual(denied_read.status_code, 200)
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(self.reservation_url).status_code, 403)
        foreign_url = reverse(
            "job-material-reservations",
            args=[self.other_organization.pk, self.job.pk],
        )
        self.client.force_login(self.other_owner)
        self.assertEqual(self.client.get(foreign_url).status_code, 404)
