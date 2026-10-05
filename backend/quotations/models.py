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
        IN_PROGRESS = "in_progress", "In progress"
        BLOCKED = "blocked", "Blocked"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

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
    due_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_jobs"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "id"]


class JobStatusHistory(models.Model):
    job = models.ForeignKey(
        Job, on_delete=models.CASCADE, related_name="status_history"
    )
    previous_status = models.CharField(max_length=16, blank=True)
    status = models.CharField(max_length=16, choices=Job.Status.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ["created_at", "id"]


class JobDueDateHistory(models.Model):
    job = models.ForeignKey(
        Job, on_delete=models.CASCADE, related_name="due_date_history"
    )
    previous_due_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class JobAssignment(models.Model):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="assignments")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="job_assignments",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_job_assignments",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    unassigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="removed_job_assignments",
        null=True,
        blank=True,
    )
    unassigned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["assigned_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "user"],
                condition=models.Q(unassigned_at__isnull=True),
                name="unique_active_job_assignment",
            )
        ]


class JobNote(models.Model):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    content = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
