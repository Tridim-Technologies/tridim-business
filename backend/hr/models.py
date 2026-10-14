from django.conf import settings
from django.db import models

from accounts.models import Membership


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
