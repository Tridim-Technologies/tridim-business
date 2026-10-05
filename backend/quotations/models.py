import uuid

from django.conf import settings
from django.db import models

from accounts.models import Organization
from customers.models import Customer


class Quotation(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"
        EXPIRED = "expired", "Expired"
        SUPERSEDED = "superseded", "Superseded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    series_id = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)
    revision_number = models.PositiveSmallIntegerField(default=1)
    supersedes = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        related_name="revision",
        null=True,
        blank=True,
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="quotations"
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="quotations"
    )
    currency = models.CharField(max_length=3)
    valid_until = models.DateField()
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.DRAFT
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_quotations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["series_id", "revision_number"],
                name="unique_quotation_series_revision",
            )
        ]

    def __str__(self):
        return f"Quotation {self.pk} ({self.status})"


class QuotationLine(models.Model):
    quotation = models.ForeignKey(
        Quotation, on_delete=models.CASCADE, related_name="lines"
    )
    description = models.CharField(max_length=240)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["quotation", "position"], name="unique_quotation_line_position"
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="quotation_line_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="quotation_line_price_nonnegative",
            ),
        ]


class QuotationStatusHistory(models.Model):
    quotation = models.ForeignKey(
        Quotation, on_delete=models.CASCADE, related_name="status_history"
    )
    previous_status = models.CharField(max_length=12, blank=True)
    status = models.CharField(max_length=12, choices=Quotation.Status.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ["created_at", "id"]


class Job(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="jobs"
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="jobs"
    )
    source_quotation = models.OneToOneField(
        Quotation, on_delete=models.PROTECT, related_name="job"
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.OPEN
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_jobs"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "id"]
