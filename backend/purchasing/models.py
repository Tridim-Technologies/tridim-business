import uuid

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

from accounts.models import Organization


def purchase_order_reference():
    return f"PO-{uuid.uuid4().hex[:16].upper()}"


class Supplier(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="suppliers"
    )
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=160)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_suppliers",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                "organization", Lower("code"), name="supplier_code_ci_org_uniq"
            )
        ]


class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ISSUED = "issued", "Issued"
        PARTIALLY_RECEIVED = "partially_received", "Partially received"
        RECEIVED = "received", "Received"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="purchase_orders"
    )
    reference = models.CharField(max_length=20, default=purchase_order_reference)
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="purchase_orders"
    )
    supplier_code = models.CharField(max_length=32)
    supplier_name = models.CharField(max_length=160)
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.DRAFT
    )
    note = models.CharField(max_length=500, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_purchase_orders",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="issued_purchase_orders",
        null=True,
        blank=True,
    )
    issued_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cancelled_purchase_orders",
        null=True,
        blank=True,
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "reference"],
                name="purchase_order_ref_org_uniq",
            )
        ]
        indexes = [models.Index(fields=["organization", "status", "created_at"])]


class PurchaseOrderLine(models.Model):
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(
        "inventory.Product",
        on_delete=models.PROTECT,
        related_name="purchase_order_lines",
    )
    product_sku = models.CharField(max_length=64)
    product_name = models.CharField(max_length=160)
    base_unit = models.CharField(max_length=16)
    ordered_quantity = models.DecimalField(max_digits=18, decimal_places=3)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["purchase_order", "product"],
                name="purchase_order_product_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(ordered_quantity__gt=0),
                name="purchase_order_line_qty_positive",
            ),
        ]


class PurchaseReceipt(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="purchase_receipts"
    )
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.PROTECT, related_name="receipts"
    )
    location = models.ForeignKey(
        "inventory.Location",
        on_delete=models.PROTECT,
        related_name="purchase_receipts",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="purchase_receipts",
    )
    idempotency_key = models.UUIDField()
    request_signature = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="purchase_receipt_request_uniq",
            )
        ]


class PurchaseReceiptLine(models.Model):
    receipt = models.ForeignKey(
        PurchaseReceipt, on_delete=models.CASCADE, related_name="lines"
    )
    order_line = models.ForeignKey(
        PurchaseOrderLine, on_delete=models.PROTECT, related_name="receipt_lines"
    )
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["receipt", "order_line"],
                name="purchase_receipt_order_line_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="purchase_receipt_line_qty_positive",
            ),
        ]
