from django.contrib import admin

from .models import Invoice, InvoiceLine, InvoiceSequence


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
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
class InvoiceAdmin(admin.ModelAdmin):
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
class InvoiceSequenceAdmin(admin.ModelAdmin):
    list_display = ("organization", "year", "next_number")
    readonly_fields = ("organization", "year", "next_number")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
