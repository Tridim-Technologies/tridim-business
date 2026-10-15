from django.conf import settings
from django.db import models
from accounts.models import Membership


class LeaveRequest(models.Model):
    class Category(models.TextChoices):
        ANNUAL = "annual", "Annual"
        PERSONAL = "personal", "Personal"
        PARENTAL = "parental", "Parental"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="leave_requests"
    )
    start_date = models.DateField()
    end_date = models.DateField()
    category = models.CharField(max_length=16, choices=Category.choices)
    note = models.CharField(max_length=500, blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_leave_requests",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "id"]
        indexes = [
            models.Index(fields=["membership", "status", "start_date"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="leave_request_dates_ordered",
            ),
        ]


class LeaveRequestHistory(models.Model):
    class Action(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    leave_request = models.ForeignKey(
        LeaveRequest, on_delete=models.CASCADE, related_name="history"
    )
    action = models.CharField(max_length=12, choices=Action.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class EmployeeProfile(models.Model):
    membership = models.OneToOneField(
        Membership, on_delete=models.CASCADE, related_name="employee_profile"
    )
    display_name = models.CharField(max_length=160)
    job_title = models.CharField(max_length=120, blank=True)
    department = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_employee_profiles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_name", "id"]

    def __str__(self):
        return f"{self.display_name} — {self.membership.organization}"
