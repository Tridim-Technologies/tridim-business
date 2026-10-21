import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from accounts.models import Membership, Organization
from .models import Location, Product, StockMovement


class InventoryTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="inventory-owner")
        self.admin = user_model.objects.create_user(username="inventory-admin")
        self.operations = user_model.objects.create_user(username="inventory-ops")
        self.sales = user_model.objects.create_user(username="inventory-sales")
        self.finance = user_model.objects.create_user(username="inventory-finance")
        self.employee = user_model.objects.create_user(username="inventory-employee")
        self.other = user_model.objects.create_user(username="inventory-other")
        self.organization = Organization.objects.create(name="Inventory Org")
        self.other_organization = Organization.objects.create(
            name="Other Inventory Org"
        )
        for user, role in (
            (self.owner, Membership.Role.OWNER),
            (self.admin, Membership.Role.ADMIN),
            (self.operations, Membership.Role.OPERATIONS),
            (self.sales, Membership.Role.SALES),
            (self.finance, Membership.Role.FINANCE),
            (self.employee, Membership.Role.EMPLOYEE),
        ):
            Membership.objects.create(
                organization=self.organization, user=user, role=role
            )
        Membership.objects.create(
            organization=self.other_organization,
            user=self.other,
            role=Membership.Role.OWNER,
        )
        self.base = f"/api/organizations/{self.organization.pk}/inventory/"
        self.product_url = reverse("inventory-products", args=[self.organization.pk])
        self.location_url = reverse("inventory-locations", args=[self.organization.pk])
        self.movement_url = reverse("inventory-movements", args=[self.organization.pk])
        self.client.force_login(self.owner)

    def request(self, method, url, data=None, *, user=None):
        if user:
            self.client.force_login(user)
        if method == "get":
            return self.client.get(url)
        return getattr(self.client, method)(
            url, data=json.dumps(data), content_type="application/json"
        )

    def create_product(self, **changes):
        response = self.request(
            "post",
            self.product_url,
            {"sku": "ITEM-01", "name": "Synthetic Item", "base_unit": "ea", **changes},
        )
        self.assertEqual(response.status_code, 201, response.content)
        return Product.objects.get(pk=response.json()["id"])

    def create_location(self, code, name):
        response = self.request("post", self.location_url, {"code": code, "name": name})
        self.assertEqual(response.status_code, 201, response.content)
        return Location.objects.get(pk=response.json()["id"])

    def movement(
        self,
        product,
        location,
        kind,
        quantity,
        *,
        destination=None,
        direction=None,
        key=None,
        reason="Synthetic inventory operation",
        user=None,
    ):
        payload = {
            "product_id": product.pk,
            "location_id": location.pk,
            "kind": kind,
            "quantity": str(quantity),
            "reason": reason,
            "idempotency_key": str(key or uuid.uuid4()),
        }
        if destination:
            payload["destination_id"] = destination.pk
        if direction:
            payload["direction"] = direction
        return self.request("post", self.movement_url, payload, user=user)

    def balance(self, product, location):
        response = self.request("get", self.base)
        product_data = next(
            item for item in response.json()["products"] if item["id"] == product.pk
        )
        return Decimal(
            next(
                row["quantity"]
                for row in product_data["balances"]
                if row["location_id"] == location.pk
            )
        )

    def test_catalog_is_tenant_scoped_case_insensitive_and_price_free(self):
        response = self.request(
            "post",
            self.product_url,
            {"sku": "sku-a", "name": "Item A", "base_unit": "kg"},
            user=self.operations,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["sku"], "SKU-A")
        self.assertNotIn("price", response.json())
        self.assertEqual(
            self.request(
                "post",
                self.product_url,
                {"sku": "SKU-a", "name": "Duplicate", "base_unit": "ea"},
            ).status_code,
            409,
        )
        self.assertEqual(
            self.request(
                "post",
                self.product_url,
                {
                    "sku": "X",
                    "name": "Client price not allowed",
                    "base_unit": "ea",
                    "price": "10.00",
                },
            ).status_code,
            400,
        )
        foreign_url = reverse("inventory", args=[self.other_organization.pk])
        foreign_response = self.request("get", foreign_url, user=self.other)
        self.assertEqual(foreign_response.status_code, 200)
        self.assertEqual(foreign_response.json()["products"], [])

    def test_receipts_issues_adjustments_and_transfers_are_idempotent_and_audited(self):
        product = self.create_product()
        first = self.create_location("MAIN", "Main store")
        second = self.create_location("SHOP", "Shop floor")

        receipt_key = uuid.uuid4()
        receipt = self.movement(product, first, "receipt", "10.125", key=receipt_key)
        self.assertEqual(receipt.status_code, 201, receipt.content)
        self.assertEqual(self.balance(product, first), Decimal("10.125"))
        duplicate = self.movement(product, first, "receipt", "10.125", key=receipt_key)
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.json()["replayed"])
        self.assertEqual(StockMovement.objects.filter(product=product).count(), 1)

        issue = self.movement(product, first, "issue", "2.125")
        self.assertEqual(issue.status_code, 201, issue.content)
        transfer = self.movement(
            product,
            first,
            "transfer",
            "3.000",
            destination=second,
            reason="Move stock to shop floor",
        )
        self.assertEqual(transfer.status_code, 201, transfer.content)
        adjustment = self.movement(
            product,
            second,
            "adjustment",
            "0.500",
            direction="increase",
            reason="Counted one additional half unit",
        )
        self.assertEqual(adjustment.status_code, 201, adjustment.content)

        self.assertEqual(self.balance(product, first), Decimal("5.000"))
        self.assertEqual(self.balance(product, second), Decimal("3.500"))
        movement = StockMovement.objects.get(pk=transfer.json()["id"])
        self.assertEqual(movement.actor, self.owner)
        self.assertEqual(movement.reason, "Move stock to shop floor")
        self.assertEqual(movement.quantity, Decimal("3.000"))

    def test_negative_stock_foreign_references_and_duplicate_key_conflict_are_denied(
        self,
    ):
        product = self.create_product()
        location = self.create_location("MAIN", "Main store")
        self.assertEqual(
            self.movement(product, location, "issue", "1").status_code, 409
        )
        foreign_product = Product.objects.create(
            organization=self.other_organization,
            sku="FOREIGN",
            name="Foreign",
            base_unit="ea",
            created_by=self.other,
        )
        self.assertEqual(
            self.movement(foreign_product, location, "receipt", "1").status_code,
            404,
        )
        key = uuid.uuid4()
        self.assertEqual(
            self.movement(product, location, "receipt", "2", key=key).status_code,
            201,
        )
        self.assertEqual(
            self.movement(product, location, "receipt", "3", key=key).status_code,
            409,
        )
        self.assertEqual(self.balance(product, location), Decimal("2.000"))

    def test_precision_shape_validation_role_scope_and_no_mutation_routes(self):
        product = self.create_product()
        location = self.create_location("MAIN", "Main store")
        base_payload = {
            "product_id": product.pk,
            "location_id": location.pk,
            "kind": "receipt",
            "quantity": 1.0,
            "reason": "Test float rejection",
            "idempotency_key": str(uuid.uuid4()),
        }
        self.assertEqual(
            self.request("post", self.movement_url, base_payload).status_code, 400
        )
        self.assertEqual(
            self.movement(product, location, "transfer", "1").status_code, 400
        )
        self.assertEqual(
            self.request("get", self.base, user=self.finance).status_code, 200
        )
        self.assertEqual(
            self.request(
                "post",
                self.product_url,
                {"sku": "FIN", "name": "Finance Cannot Create", "base_unit": "ea"},
                user=self.finance,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.request("get", self.base, user=self.employee).status_code, 403
        )
        detail_url = reverse(
            "inventory-product-detail", args=[self.organization.pk, product.pk]
        )
        self.assertEqual(self.request("delete", detail_url).status_code, 405)
        self.assertEqual(self.request("patch", self.movement_url, {}).status_code, 405)

    def test_inventory_read_and_write_role_matrix(self):
        product = self.create_product()
        location = self.create_location("ROLE-MATRIX", "Role matrix store")

        for user in (
            self.owner,
            self.admin,
            self.operations,
            self.sales,
            self.finance,
        ):
            with self.subTest(read_role=user.username):
                self.assertEqual(
                    self.request("get", self.base, user=user).status_code, 200
                )
                self.assertEqual(
                    self.request("get", self.movement_url, user=user).status_code, 200
                )
        self.assertEqual(
            self.request("get", self.base, user=self.employee).status_code, 403
        )

        allowed = (self.owner, self.admin, self.operations)
        for index, user in enumerate(allowed):
            with self.subTest(write_role=user.username):
                movement = self.movement(
                    product,
                    location,
                    "receipt",
                    "1.000",
                    user=user,
                )
                self.assertEqual(movement.status_code, 201, movement.content)
                self.assertEqual(movement.json()["actor"], user.username)
                created_product = self.request(
                    "post",
                    self.product_url,
                    {
                        "sku": f"ROLE-{index}",
                        "name": f"Role matrix item {index}",
                        "base_unit": "ea",
                    },
                    user=user,
                )
                self.assertEqual(
                    created_product.status_code, 201, created_product.content
                )
                created_location = self.request(
                    "post",
                    self.location_url,
                    {"code": f"ROLE-{index}", "name": f"Role matrix location {index}"},
                    user=user,
                )
                self.assertEqual(
                    created_location.status_code, 201, created_location.content
                )

        product_detail = reverse(
            "inventory-product-detail", args=[self.organization.pk, product.pk]
        )
        location_detail = reverse(
            "inventory-location-detail", args=[self.organization.pk, location.pk]
        )
        counts = (
            Product.objects.filter(organization=self.organization).count(),
            Location.objects.filter(organization=self.organization).count(),
            StockMovement.objects.filter(organization=self.organization).count(),
        )
        for user in (self.sales, self.finance, self.employee):
            with self.subTest(denied_write_role=user.username):
                responses = (
                    self.movement(product, location, "receipt", "1.000", user=user),
                    self.request(
                        "post",
                        self.product_url,
                        {
                            "sku": f"DENIED-{user.pk}",
                            "name": "Denied",
                            "base_unit": "ea",
                        },
                        user=user,
                    ),
                    self.request(
                        "patch", product_detail, {"name": "Denied change"}, user=user
                    ),
                    self.request(
                        "post",
                        self.location_url,
                        {"code": f"DENIED-{user.pk}", "name": "Denied"},
                        user=user,
                    ),
                    self.request(
                        "patch", location_detail, {"name": "Denied change"}, user=user
                    ),
                )
                self.assertEqual(
                    [response.status_code for response in responses], [403] * 5
                )
                self.assertEqual(
                    (
                        Product.objects.filter(organization=self.organization).count(),
                        Location.objects.filter(organization=self.organization).count(),
                        StockMovement.objects.filter(
                            organization=self.organization
                        ).count(),
                    ),
                    counts,
                )
                product.refresh_from_db()
                location.refresh_from_db()
                self.assertEqual(product.name, "Synthetic Item")
                self.assertEqual(location.name, "Role matrix store")
                self.client.force_login(self.owner)
                self.assertEqual(self.balance(product, location), Decimal("3.000"))

    def test_unit_changes_after_movement_and_location_deactivation_with_stock_are_blocked(
        self,
    ):
        product = self.create_product()
        location = self.create_location("MAIN", "Main store")
        self.assertEqual(
            self.movement(product, location, "receipt", "1").status_code, 201
        )
        product_url = reverse(
            "inventory-product-detail", args=[self.organization.pk, product.pk]
        )
        self.assertEqual(
            self.request("patch", product_url, {"base_unit": "kg"}).status_code,
            409,
        )
        location_url = reverse(
            "inventory-location-detail", args=[self.organization.pk, location.pk]
        )
        self.assertEqual(
            self.request("patch", location_url, {"is_active": False}).status_code,
            409,
        )
        self.assertEqual(self.balance(product, location), Decimal("1.000"))


@skipUnless(
    connection.features.has_select_for_update,
    "The configured test database does not support row-level locking.",
)
class InventoryConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="inventory-lock-owner")
        self.operations = user_model.objects.create_user(username="inventory-lock-ops")
        self.organization = Organization.objects.create(name="Inventory Lock Org")
        for user, role in (
            (self.owner, Membership.Role.OWNER),
            (self.operations, Membership.Role.OPERATIONS),
        ):
            Membership.objects.create(
                organization=self.organization, user=user, role=role
            )
        self.product = Product.objects.create(
            organization=self.organization,
            sku="LOCK-1",
            name="Lock Test Item",
            base_unit="ea",
            created_by=self.owner,
        )
        self.location = Location.objects.create(
            organization=self.organization,
            code="LOCK",
            name="Lock Test Location",
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
        self.url = reverse("inventory-movements", args=[self.organization.pk])

    def test_concurrent_issues_cannot_overdraw_stock(self):
        barrier = Barrier(2)

        def issue(user):
            close_old_connections()
            try:
                client = self.client_class()
                client.force_login(user)
                barrier.wait(timeout=10)
                response = client.post(
                    self.url,
                    data=json.dumps(
                        {
                            "product_id": self.product.pk,
                            "kind": "issue",
                            "location_id": self.location.pk,
                            "quantity": "0.750",
                            "reason": "Concurrent synthetic issue",
                            "idempotency_key": str(uuid.uuid4()),
                        }
                    ),
                    content_type="application/json",
                )
                return response.status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(issue, user) for user in (self.owner, self.operations)
            ]
            statuses = sorted(future.result(timeout=30) for future in futures)
        self.assertEqual(statuses, [201, 409])
        self.client.force_login(self.owner)
        summary = self.client.get(
            reverse("inventory", args=[self.organization.pk])
        ).json()
        product = next(
            item for item in summary["products"] if item["id"] == self.product.pk
        )
        self.assertEqual(product["balances"][0]["quantity"], "0.250")
