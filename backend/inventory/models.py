from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

from accounts.models import Organization


class Product(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="inventory_products"
    )
    sku = models.CharField(max_length=64)
    name = models.CharField(max_length=160)
    base_unit = models.CharField(max_length=16)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_inventory_products",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                "organization", Lower("sku"), name="inventory_sku_ci_org_uniq"
            )
        ]


class Location(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="inventory_locations"
    )
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_inventory_locations",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                "organization", Lower("code"), name="inventory_loc_ci_org_uniq"
            )
        ]


class StockMovement(models.Model):
    class Kind(models.TextChoices):
        RECEIPT = "receipt", "Receipt"
        ISSUE = "issue", "Issue"
        ADJUSTMENT = "adjustment", "Adjustment"
        TRANSFER = "transfer", "Transfer"

    class Direction(models.TextChoices):
        INCREASE = "increase", "Increase"
        DECREASE = "decrease", "Decrease"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="stock_movements"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="stock_movements"
    )
    kind = models.CharField(max_length=12, choices=Kind.choices)
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="outgoing_movements"
    )
    destination = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        related_name="incoming_movements",
        null=True,
        blank=True,
    )
    direction = models.CharField(
        max_length=8, choices=Direction.choices, blank=True, default=""
    )
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    reason = models.CharField(max_length=500)
    idempotency_key = models.UUIDField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="inventory_movements",
    )
    source_receipt_line = models.OneToOneField(
        "purchasing.PurchaseReceiptLine",
        on_delete=models.PROTECT,
        related_name="stock_movement",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="inventory_movement_request_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="inventory_qty_positive"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        kind="transfer",
                        destination__isnull=False,
                        direction="",
                    )
                    & ~models.Q(location=models.F("destination"))
                )
                | models.Q(
                    kind="adjustment",
                    destination__isnull=True,
                    direction__in=["increase", "decrease"],
                )
                | models.Q(
                    kind__in=["receipt", "issue"],
                    destination__isnull=True,
                    direction="",
                ),
                name="inventory_movement_shape_valid",
            ),
        ]
