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


class JobTimeEntry(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="time_entries")
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="job_time_entries",
    )
    work_date = models.DateField()
    hours = models.DecimalField(max_digits=4, decimal_places=2)
    description = models.CharField(max_length=1000, blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.SUBMITTED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-work_date", "-created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(hours__gt=0) & models.Q(hours__lte=24),
                name="job_time_entry_hours_valid",
            )
        ]


class JobTimeEntryHistory(models.Model):
    entry = models.ForeignKey(
        JobTimeEntry, on_delete=models.CASCADE, related_name="history"
    )
    previous_status = models.CharField(max_length=12, blank=True)
    status = models.CharField(max_length=12, choices=JobTimeEntry.Status.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    work_date = models.DateField()
    hours = models.DecimalField(max_digits=4, decimal_places=2)
    description = models.CharField(max_length=1000, blank=True)
    reason = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class ExpenseClaim(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        RETURNED = "returned", "Returned"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    class Category(models.TextChoices):
        TRAVEL = "travel", "Travel"
        MEALS = "meals", "Meals"
        MATERIALS = "materials", "Materials"
        OTHER = "other", "Other"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="expense_claims"
    )
    job = models.ForeignKey(
        Job, on_delete=models.PROTECT, related_name="expense_claims"
    )
    claimant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="expense_claims",
    )
    expense_date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=5)
    currency = models.CharField(max_length=3)
    category = models.CharField(max_length=12, choices=Category.choices)
    merchant = models.CharField(max_length=160, blank=True)
    purpose = models.CharField(max_length=1000)
    missing_receipt_explanation = models.CharField(max_length=500, blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.DRAFT
    )
    version = models.PositiveIntegerField(default=1)
    revision = models.PositiveIntegerField(default=1)
    waived_version = models.PositiveIntegerField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="expense_claim_amount_positive"
            )
        ]


class ExpenseClaimHistory(models.Model):
    claim = models.ForeignKey(
        ExpenseClaim, on_delete=models.CASCADE, related_name="history"
    )
    action = models.CharField(max_length=16)
    previous_status = models.CharField(max_length=12, blank=True)
    status = models.CharField(max_length=12, choices=ExpenseClaim.Status.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    version = models.PositiveIntegerField()
    revision = models.PositiveIntegerField()
    expense_date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=5)
    currency = models.CharField(max_length=3)
    category = models.CharField(max_length=12, choices=ExpenseClaim.Category.choices)
    merchant = models.CharField(max_length=160, blank=True)
    purpose = models.CharField(max_length=1000)
    missing_receipt_explanation = models.CharField(max_length=500, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class ExpenseClaimEvidence(models.Model):
    class State(models.TextChoices):
        QUARANTINED = "quarantined", "Quarantined"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        DELETED = "deleted", "Deleted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="expense_evidence"
    )
    claim = models.ForeignKey(
        ExpenseClaim, on_delete=models.CASCADE, related_name="evidence"
    )
    claim_version = models.PositiveIntegerField()
    storage_key = models.CharField(max_length=32, unique=True)
    state = models.CharField(max_length=12, choices=State.choices)
    detected_media_type = models.CharField(max_length=32)
    size_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_expense_evidence",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["claim", "claim_version", "state"]),
            models.Index(fields=["state", "created_at"]),
            models.Index(fields=["state", "accepted_at"]),
        ]


class ExpenseEvidenceAuditEvent(models.Model):
    class Action(models.TextChoices):
        QUARANTINE = "quarantine", "Quarantined"
        SCAN_CLEAN = "scan_clean", "Scan clean"
        SCAN_REJECTED = "scan_rejected", "Scan rejected"
        SCAN_ERROR = "scan_error", "Scan error"
        DOWNLOAD = "download", "Downloaded"
        DELETE = "delete", "Deleted"
        RETENTION_EXPIRE = "retention_expire", "Retention expiry"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="expense_evidence_audit"
    )
    claim = models.ForeignKey(
        ExpenseClaim, on_delete=models.CASCADE, related_name="evidence_audit"
    )
    evidence = models.ForeignKey(
        ExpenseClaimEvidence,
        on_delete=models.SET_NULL,
        related_name="audit_events",
        null=True,
        blank=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=16, choices=Action.choices)
    outcome = models.CharField(max_length=16)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
