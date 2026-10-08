import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        SALES = "sales", "Sales"
        OPERATIONS = "operations", "Operations"
        FINANCE = "finance", "Finance"
        EMPLOYEE = "employee", "Employee"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="organization_memberships",
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"], name="unique_org_user_membership"
            )
        ]

    def __str__(self):
        return f"{self.user} — {self.organization} ({self.role})"


class SupportAccess(models.Model):
    """A time-limited grant for read-only support access to one organization."""

    class Scope(models.TextChoices):
        CUSTOMERS = "customers", "Customer records"
        SALES = "sales", "Quotations"
        DELIVERY = "delivery", "Jobs and delivery history"
        FINANCE = "finance", "Invoices and sequences"
        PAYMENTS = "payments", "Daraja payment diagnostics"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="support_access_grants",
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="support_access_grants"
    )
    scope = models.CharField(max_length=16, choices=Scope.choices)
    purpose = models.CharField(max_length=500)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="granted_support_access",
    )
    granted_at = models.DateTimeField(default=timezone.now, editable=False)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-granted_at", "id"]

    def clean(self):
        super().clean()
        if (
            self._state.adding
            and self.user_id
            and (
                self.user.is_superuser
                or not self.user.is_staff
                or not self.user.is_active
            )
        ):
            raise ValidationError(
                {"user": "Support access requires a non-superuser staff account."}
            )
        if (
            self._state.adding
            and self.granted_by_id
            and not self.granted_by.is_superuser
        ):
            raise ValidationError(
                {"granted_by": "Only a platform superuser may grant support access."}
            )
        if self.expires_at and self.granted_at:
            if self.expires_at <= self.granted_at:
                raise ValidationError({"expires_at": "Expiry must follow grant time."})
            if self.expires_at > self.granted_at + timedelta(hours=8):
                raise ValidationError(
                    {"expires_at": "Support access cannot exceed eight hours."}
                )
        if not self.purpose.strip():
            raise ValidationError({"purpose": "A support purpose is required."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @classmethod
    def active_for(cls, user, *, now=None):
        now = now or timezone.now()
        return cls.objects.filter(
            user=user, revoked_at__isnull=True, granted_at__lte=now, expires_at__gt=now
        )

    def __str__(self):
        return (
            f"{self.organization} — {self.get_scope_display()} — {self.user} "
            f"until {self.expires_at:%Y-%m-%d %H:%M} UTC"
        )


class SupportAccessAuditEvent(models.Model):
    class AccessType(models.TextChoices):
        LIST = "list", "List viewed"
        OBJECT = "object", "Record viewed"

    support_access = models.ForeignKey(
        SupportAccess, on_delete=models.PROTECT, related_name="audit_events"
    )
    accessed_at = models.DateTimeField(default=timezone.now, editable=False)
    model_label = models.CharField(max_length=100)
    object_pk = models.CharField(max_length=100, blank=True)
    access_type = models.CharField(max_length=12, choices=AccessType.choices)

    class Meta:
        ordering = ["-accessed_at", "id"]

    def __str__(self):
        return f"{self.access_type}: {self.model_label} at {self.accessed_at:%Y-%m-%d %H:%M UTC}"
