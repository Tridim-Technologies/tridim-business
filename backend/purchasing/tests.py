import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization
from inventory.models import Location, Product, StockMovement

from .models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseReceipt,
    PurchaseReceiptLine,
    Supplier,
)


class PurchasingTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="purchasing-owner")
        self.operations = user_model.objects.create_user(username="purchasing-ops")
        self.finance = user_model.objects.create_user(username="purchasing-finance")
        self.employee = user_model.objects.create_user(username="purchasing-employee")
        self.other = user_model.objects.create_user(username="purchasing-other")
        self.organization = Organization.objects.create(name="Purchasing Org")
        self.other_organization = Organization.objects.create(
            name="Other Purchasing Org"
        )
        for user, role in (
            (self.owner, Membership.Role.OWNER),
            (self.operations, Membership.Role.OPERATIONS),
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
        self.base = f"/api/organizations/{self.organization.pk}/purchasing/"
        self.suppliers_url = reverse(
            "purchasing-suppliers", args=[self.organization.pk]
        )
        self.orders_url = reverse("purchase-orders", args=[self.organization.pk])
        self.product = Product.objects.create(
            organization=self.organization,
            sku="ITEM-1",
            name="Synthetic item",
            base_unit="ea",
            created_by=self.owner,
        )
        self.location = Location.objects.create(
            organization=self.organization,
            code="MAIN",
            name="Main store",
            created_by=self.owner,
        )
        self.client.force_login(self.owner)

    def request(self, method, url, payload=None, *, user=None):
        if user:
            self.client.force_login(user)
        if method == "get":
            return self.client.get(url)
        if method == "delete":
            return self.client.delete(url)
        return getattr(self.client, method)(
            url,
            data=json.dumps(payload or {}),
            content_type="application/json",
        )

    def create_supplier(self, code="SUP-1", name="Synthetic supplier", **fields):
        response = self.request(
            "post", self.suppliers_url, {"code": code, "name": name, **fields}
        )
        self.assertEqual(response.status_code, 201, response.content)
        return Supplier.objects.get(pk=response.json()["id"])

    def create_order(self, supplier=None, *, quantity="5.000", lines=None):
        supplier = supplier or self.create_supplier()
        response = self.request(
            "post",
            self.orders_url,
            {
                "supplier_id": supplier.pk,
                "note": "Synthetic stock replenishment",
                "lines": lines
                or [{"product_id": self.product.pk, "ordered_quantity": quantity}],
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def issue(self, order):
        return self.request(
            "post",
            reverse("purchase-order-issue", args=[self.organization.pk, order["id"]]),
        )

    def receive(self, order, lines, *, key=None, location=None):
        return self.request(
            "post",
            reverse(
                "purchase-order-receipts",
                args=[self.organization.pk, order["id"]],
            ),
            {
                "location_id": (location or self.location).pk,
                "idempotency_key": str(key or uuid.uuid4()),
                "lines": lines,
            },
        )

    def order_line_id(self, order):
        return order["lines"][0]["id"]

    def test_supplier_is_tenant_scoped_case_insensitive_and_role_restricted(self):
        response = self.request(
            "post",
            self.suppliers_url,
            {"code": "vendor-a", "name": "Synthetic vendor"},
            user=self.operations,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["code"], "VENDOR-A")
        self.assertEqual(
            self.request(
                "post",
                self.suppliers_url,
                {"code": "VENDOR-A", "name": "Duplicate"},
            ).status_code,
            409,
        )
        self.assertEqual(
            self.request(
                "post",
                self.suppliers_url,
                {"code": "EXTRA", "name": "Unknown key", "email": "a@b.test"},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.request(
                "post",
                self.suppliers_url,
                {"code": "EMP", "name": "Denied"},
                user=self.employee,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.request("get", self.base, user=self.finance).status_code, 200
        )
        self.assertEqual(
            self.request("get", self.base, user=self.employee).status_code, 403
        )
        self.assertEqual(
            self.request("get", self.base, user=self.other).status_code, 404
        )

    def test_draft_order_is_editable_then_issue_freezes_it_and_issue_retry_is_safe(
        self,
    ):
        supplier = self.create_supplier()
        order = self.create_order(supplier)
        self.assertEqual(order["status"], PurchaseOrder.Status.DRAFT)
        self.assertTrue(order["reference"].startswith("PO-"))
        self.assertEqual(order["supplier_name"], supplier.name)

        update = self.request(
            "patch",
            reverse("purchase-order-detail", args=[self.organization.pk, order["id"]]),
            {
                "supplier_id": supplier.pk,
                "note": "Updated synthetic order",
                "lines": [{"product_id": self.product.pk, "ordered_quantity": "6.000"}],
            },
        )
        self.assertEqual(update.status_code, 200, update.content)
        self.assertEqual(update.json()["lines"][0]["ordered_quantity"], "6.000")

        issued = self.issue(order)
        self.assertEqual(issued.status_code, 200, issued.content)
        self.assertEqual(issued.json()["status"], PurchaseOrder.Status.ISSUED)
        self.assertEqual(self.issue(order).status_code, 200)
        self.assertEqual(
            self.request(
                "patch",
                reverse(
                    "purchase-order-detail", args=[self.organization.pk, order["id"]]
                ),
                {
                    "supplier_id": supplier.pk,
                    "lines": [
                        {"product_id": self.product.pk, "ordered_quantity": "9.000"}
                    ],
                },
            ).status_code,
            409,
        )

    def test_partial_and_full_receipts_create_linked_immutable_stock_movements(self):
        order = self.create_order(quantity="5.000")
        self.assertEqual(self.issue(order).status_code, 200)
        order_line_id = self.order_line_id(order)
        first_key = uuid.uuid4()
        first = self.receive(
            order,
            [{"order_line_id": order_line_id, "quantity": "2.000"}],
            key=first_key,
        )
        self.assertEqual(first.status_code, 201, first.content)
        self.assertFalse(first.json()["replayed"])
        self.assertEqual(first.json()["lines"][0]["quantity"], "2.000")
        self.assertEqual(first.json()["lines"][0]["movement_id"] > 0, True)

        replay = self.receive(
            order,
            [{"order_line_id": order_line_id, "quantity": "2.000"}],
            key=first_key,
        )
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()["replayed"])
        self.assertEqual(PurchaseReceipt.objects.count(), 1)
        self.assertEqual(StockMovement.objects.filter(product=self.product).count(), 1)

        listing = self.request("get", self.base).json()
        api_order = next(
            item for item in listing["orders"] if item["id"] == order["id"]
        )
        self.assertEqual(api_order["status"], PurchaseOrder.Status.PARTIALLY_RECEIVED)
        self.assertEqual(api_order["lines"][0]["received_quantity"], "2.000")
        self.assertEqual(api_order["receipts"][0]["id"], first.json()["id"])

        second = self.receive(
            order, [{"order_line_id": order_line_id, "quantity": "3.000"}]
        )
        self.assertEqual(second.status_code, 201, second.content)
        listing = self.request("get", self.base).json()
        api_order = next(
            item for item in listing["orders"] if item["id"] == order["id"]
        )
        self.assertEqual(api_order["status"], PurchaseOrder.Status.RECEIVED)
        self.assertEqual(api_order["lines"][0]["remaining_quantity"], "0.000")
        self.assertEqual(
            sum(
                (
                    movement.quantity
                    for movement in StockMovement.objects.filter(product=self.product)
                ),
                Decimal("0"),
            ),
            Decimal("5.000"),
        )
        linked = StockMovement.objects.filter(
            source_receipt_line__receipt__purchase_order_id=order["id"]
        )
        self.assertEqual(linked.count(), 2)
        self.assertEqual(
            linked.first().source_receipt_line.receipt.purchase_order.reference,
            order["reference"],
        )
        inventory = self.request(
            "get", f"/api/organizations/{self.organization.pk}/inventory/"
        ).json()
        listed_movement = next(
            item for item in inventory["movements"] if item["id"] == linked.first().pk
        )
        self.assertEqual(
            listed_movement["supplier_order_reference"], order["reference"]
        )

    def test_over_receipt_cross_tenant_ids_and_idempotency_conflicts_do_not_mutate(
        self,
    ):
        order = self.create_order(quantity="4.000")
        self.issue(order)
        order_line_id = self.order_line_id(order)
        key = uuid.uuid4()
        response = self.receive(
            order, [{"order_line_id": order_line_id, "quantity": "4.001"}], key=key
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(PurchaseReceipt.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)

        created = self.receive(
            order, [{"order_line_id": order_line_id, "quantity": "1.000"}], key=key
        )
        self.assertEqual(created.status_code, 201)
        conflict = self.receive(
            order, [{"order_line_id": order_line_id, "quantity": "2.000"}], key=key
        )
        self.assertEqual(conflict.status_code, 409)

        foreign_location = Location.objects.create(
            organization=self.other_organization,
            code="FOREIGN",
            name="Foreign location",
            created_by=self.other,
        )
        self.assertEqual(
            self.receive(
                order,
                [{"order_line_id": order_line_id, "quantity": "1.000"}],
                location=foreign_location,
            ).status_code,
            404,
        )
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_cross_tenant_products_and_suppliers_are_rejected(self):
        foreign_product = Product.objects.create(
            organization=self.other_organization,
            sku="FOREIGN",
            name="Foreign product",
            base_unit="ea",
            created_by=self.other,
        )
        supplier = self.create_supplier()
        response = self.request(
            "post",
            self.orders_url,
            {
                "supplier_id": supplier.pk,
                "lines": [
                    {"product_id": foreign_product.pk, "ordered_quantity": "1.000"}
                ],
            },
        )
        self.assertEqual(response.status_code, 404)
        foreign_supplier = Supplier.objects.create(
            organization=self.other_organization,
            code="FOREIGN-S",
            name="Foreign Supplier",
            created_by=self.other,
        )
        response = self.request(
            "post",
            self.orders_url,
            {
                "supplier_id": foreign_supplier.pk,
                "lines": [{"product_id": self.product.pk, "ordered_quantity": "1.000"}],
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(PurchaseOrder.objects.count(), 0)

    def test_cancelled_partial_order_keeps_received_stock_and_blocks_more_receiving(
        self,
    ):
        order = self.create_order(quantity="5.000")
        self.issue(order)
        line_id = self.order_line_id(order)
        receipt = self.receive(order, [{"order_line_id": line_id, "quantity": "1.000"}])
        self.assertEqual(receipt.status_code, 201)
        cancel = self.request(
            "post",
            reverse("purchase-order-cancel", args=[self.organization.pk, order["id"]]),
        )
        self.assertEqual(cancel.status_code, 200)
        self.assertEqual(cancel.json()["status"], PurchaseOrder.Status.CANCELLED)
        self.assertEqual(cancel.json()["lines"][0]["received_quantity"], "1.000")
        self.assertEqual(
            self.receive(
                order, [{"order_line_id": line_id, "quantity": "1.000"}]
            ).status_code,
            409,
        )
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(
            self.request(
                "post",
                reverse(
                    "purchase-order-cancel", args=[self.organization.pk, order["id"]]
                ),
            ).status_code,
            200,
        )

    def test_draft_deletion_empty_order_and_unit_change_guard(self):
        supplier = self.create_supplier()
        empty = self.request(
            "post", self.orders_url, {"supplier_id": supplier.pk, "lines": []}
        )
        self.assertEqual(empty.status_code, 400)
        draft = self.create_order(supplier)
        url = reverse("purchase-order-detail", args=[self.organization.pk, draft["id"]])
        product_url = reverse(
            "inventory-product-detail", args=[self.organization.pk, self.product.pk]
        )
        self.assertEqual(
            self.request("patch", product_url, {"base_unit": "kg"}).status_code, 409
        )
        self.assertEqual(
            self.request("patch", product_url, {"is_active": False}).status_code, 200
        )
        self.assertEqual(self.issue(draft).status_code, 409)
        self.assertEqual(self.request("delete", url).status_code, 204)
        self.assertFalse(PurchaseOrder.objects.filter(pk=draft["id"]).exists())

    def test_receipt_transaction_rolls_back_when_a_stock_movement_cannot_be_written(
        self,
    ):
        order = self.create_order(quantity="2.000")
        self.issue(order)
        self.client.raise_request_exception = False
        with patch(
            "purchasing.views.StockMovement.objects.create", side_effect=RuntimeError
        ):
            response = self.receive(
                order,
                [{"order_line_id": self.order_line_id(order), "quantity": "1.000"}],
            )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(PurchaseReceipt.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)
        order_model = PurchaseOrder.objects.get(pk=order["id"])
        self.assertEqual(order_model.status, PurchaseOrder.Status.ISSUED)


@skipUnless(
    connection.features.has_select_for_update,
    "The configured test database does not support row-level locking.",
)
class PurchaseReceivingConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="purchase-lock-owner")
        self.operations = user_model.objects.create_user(username="purchase-lock-ops")
        self.organization = Organization.objects.create(name="Purchase Lock Org")
        for user, role in (
            (self.owner, Membership.Role.OWNER),
            (self.operations, Membership.Role.OPERATIONS),
        ):
            Membership.objects.create(
                organization=self.organization, user=user, role=role
            )
        supplier = Supplier.objects.create(
            organization=self.organization,
            code="LOCK-SUP",
            name="Synthetic lock supplier",
            created_by=self.owner,
        )
        product = Product.objects.create(
            organization=self.organization,
            sku="LOCK-ITEM",
            name="Lock test item",
            base_unit="ea",
            created_by=self.owner,
        )
        location = Location.objects.create(
            organization=self.organization,
            code="LOCK-LOC",
            name="Lock test location",
            created_by=self.owner,
        )
        order = PurchaseOrder.objects.create(
            organization=self.organization,
            supplier=supplier,
            supplier_code=supplier.code,
            supplier_name=supplier.name,
            status=PurchaseOrder.Status.ISSUED,
            created_by=self.owner,
            issued_by=self.owner,
            issued_at=timezone.now(),
        )
        self.order_line = PurchaseOrderLine.objects.create(
            purchase_order=order,
            product=product,
            product_sku=product.sku,
            product_name=product.name,
            base_unit=product.base_unit,
            ordered_quantity=Decimal("1.000"),
        )
        self.location = location
        self.order = order
        self.url = reverse(
            "purchase-order-receipts", args=[self.organization.pk, self.order.pk]
        )

    def test_concurrent_receipts_cannot_over_receive_an_order_line(self):
        barrier = Barrier(2)

        def receive(user):
            close_old_connections()
            try:
                client = self.client_class()
                client.force_login(user)
                barrier.wait(timeout=10)
                response = client.post(
                    self.url,
                    data=json.dumps(
                        {
                            "location_id": self.location.pk,
                            "idempotency_key": str(uuid.uuid4()),
                            "lines": [
                                {
                                    "order_line_id": self.order_line.pk,
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
                executor.submit(receive, user) for user in (self.owner, self.operations)
            ]
            statuses = sorted(future.result(timeout=30) for future in futures)
        self.assertEqual(statuses, [201, 409])
        total_received = sum(
            PurchaseReceiptLine.objects.filter(order_line=self.order_line).values_list(
                "quantity", flat=True
            ),
            Decimal("0"),
        )
        self.assertEqual(total_received, Decimal("0.750"))
        self.assertEqual(
            StockMovement.objects.filter(product=self.order_line.product).count(), 1
        )
