from django.contrib import admin

from accounts.support_admin import (
    SupportReadOnlyTabularInline,
    SupportScopedReadOnlyAdmin,
)
from .models import (
    DarajaCallbackEvent,
    DarajaPaymentAttempt,
    Invoice,
    InvoiceLine,
    InvoiceSequence,
)


class InvoiceLineInline(SupportReadOnlyTabularInline):
    model = InvoiceLine
    support_scope = "finance"
    extra = 0
    can_delete = False
    readonly_fields = (
        "invoice",
        "description",
        "quantity",
        "unit_price",
        "line_total",
        "position",
    )


@admin.register(Invoice)
class InvoiceAdmin(SupportScopedReadOnlyAdmin):
    organization_lookup = "organization_id"
    support_scope = "finance"
    list_display = (
        "invoice_number",
        "customer",
        "organization",
        "status",
        "issue_date",
        "due_date",
        "currency",
        "total",
    )
    list_filter = ("organization", "status", "currency", "issue_date")
    search_fields = ("invoice_number", "customer__name", "job__id")
    readonly_fields = (
        "organization",
        "job",
        "source_quotation",
        "customer",
        "customer_name",
        "replaces",
        "invoice_number",
        "status",
        "issue_date",
        "due_date",
        "currency",
        "total",
        "issued_by",
        "issued_at",
        "correction_reason",
        "void_reason",
        "voided_by",
        "voided_at",
    )
    inlines = (InvoiceLineInline,)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(InvoiceSequence)
class InvoiceSequenceAdmin(SupportScopedReadOnlyAdmin):
    organization_lookup = "organization_id"
    support_scope = "finance"
    list_display = ("organization", "year", "next_number")
    readonly_fields = ("organization", "year", "next_number")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DarajaPaymentAttempt)
class DarajaPaymentAttemptAdmin(SupportScopedReadOnlyAdmin):
    organization_lookup = "organization_id"
    support_scope = "payments"
    list_display = (
        "id",
        "organization",
        "invoice",
        "amount",
        "status",
        "checkout_request_id",
        "created_at",
    )
    list_filter = ("status", "organization", "created_at")
    search_fields = (
        "checkout_request_id",
        "merchant_request_id",
        "invoice__invoice_number",
    )
    readonly_fields = tuple(field.name for field in DarajaPaymentAttempt._meta.fields)

    def get_fields(self, request, obj=None):
        if request.user.is_superuser:
            return super().get_fields(request, obj)
        return tuple(
            field.name
            for field in DarajaPaymentAttempt._meta.fields
            if field.name not in {"phone_number", "response_data"}
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DarajaCallbackEvent)
class DarajaCallbackEventAdmin(SupportScopedReadOnlyAdmin):
    organization_lookup = "attempt__organization_id"
    support_scope = "payments"
    list_display = (
        "checkout_request_id",
        "attempt",
        "delivery_count",
        "received_at",
        "processed_at",
    )
    list_filter = ("received_at", "processed_at")
    search_fields = ("checkout_request_id",)
    readonly_fields = tuple(field.name for field in DarajaCallbackEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
