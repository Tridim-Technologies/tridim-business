from django.contrib import admin

from accounts.support_admin import SupportScopedReadOnlyAdmin
from .models import Customer


@admin.register(Customer)
class CustomerAdmin(SupportScopedReadOnlyAdmin):
    organization_lookup = "organization_id"
    support_scope = "customers"
    list_display = ("name", "organization", "email", "created_at")
    list_filter = ("organization",)
    search_fields = ("name", "contact_name", "email", "phone")
