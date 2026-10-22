from decimal import Decimal

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
    reorder_point = models.DecimalField(
        max_digits=18, decimal_places=3, default=Decimal("0.000")
    )
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
            ),
            models.CheckConstraint(
                condition=models.Q(reorder_point__gte=0),
                name="inventory_reorder_point_nonnegative",
            ),
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
    source_job_material_issue_line = models.OneToOneField(
        "inventory.JobMaterialIssueLine",
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


class JobMaterialIssue(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="job_material_issues"
    )
    job = models.ForeignKey(
        "quotations.Job", on_delete=models.PROTECT, related_name="material_issues"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="job_material_issues",
    )
    idempotency_key = models.UUIDField()
    request_signature = models.CharField(max_length=64)
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="job_material_issue_request_uniq",
            )
        ]


class JobMaterialIssueLine(models.Model):
    issue = models.ForeignKey(
        JobMaterialIssue, on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="job_material_issue_lines"
    )
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="job_material_issue_lines"
    )
    reservation_line = models.ForeignKey(
        "inventory.JobMaterialReservationLine",
        on_delete=models.PROTECT,
        related_name="material_issue_lines",
        null=True,
        blank=True,
    )
    product_sku = models.CharField(max_length=64)
    product_name = models.CharField(max_length=160)
    base_unit = models.CharField(max_length=16)
    location_code = models.CharField(max_length=32)
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="job_material_qty_positive"
            )
        ]


class JobMaterialReservation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        RELEASED = "released", "Released"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="job_material_reservations"
    )
    job = models.ForeignKey(
        "quotations.Job", on_delete=models.PROTECT, related_name="material_reservations"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="job_material_reservations",
    )
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="released_job_material_reservations",
        null=True,
        blank=True,
    )
    idempotency_key = models.UUIDField()
    request_signature = models.CharField(max_length=64)
    reason = models.CharField(max_length=500)
    status = models.CharField(
        max_length=8, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="job_material_reserve_request_uniq",
            )
        ]


class JobMaterialReservationLine(models.Model):
    reservation = models.ForeignKey(
        JobMaterialReservation, on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="job_material_reservation_lines"
    )
    location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        related_name="job_material_reservation_lines",
    )
    product_sku = models.CharField(max_length=64)
    product_name = models.CharField(max_length=160)
    base_unit = models.CharField(max_length=16)
    location_code = models.CharField(max_length=32)
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["reservation", "product", "location"],
                name="job_reservation_product_location_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="job_reservation_qty_positive"
            ),
        ]
