from django.contrib import admin

from accounts.support_admin import (
    SupportReadOnlyTabularInline,
    SupportScopedReadOnlyAdmin,
)
from .models import (
    Job,
    JobAssignment,
    JobDueDateHistory,
    JobNote,
    JobStatusHistory,
    Quotation,
    QuotationLine,
    QuotationStatusHistory,
)


class QuotationLineInline(SupportReadOnlyTabularInline):
    model = QuotationLine
    support_scope = "sales"
    extra = 0


class QuotationStatusHistoryInline(SupportReadOnlyTabularInline):
    model = QuotationStatusHistory
    support_scope = "sales"
    extra = 0
    can_delete = False
    readonly_fields = ("previous_status", "status", "actor", "created_at", "note")


@admin.register(Quotation)
class QuotationAdmin(SupportScopedReadOnlyAdmin):
    organization_lookup = "organization_id"
    support_scope = "sales"
    list_display = ("id", "customer", "organization", "status", "valid_until")
    list_filter = ("organization", "status", "currency")
    search_fields = ("customer__name", "id")
    inlines = (QuotationLineInline, QuotationStatusHistoryInline)


@admin.register(Job)
class JobAdmin(SupportScopedReadOnlyAdmin):
    organization_lookup = "organization_id"
    support_scope = "delivery"
    list_display = ("id", "customer", "organization", "status", "created_at")
    list_filter = ("organization", "status")
    readonly_fields = (
        "organization",
        "customer",
        "source_quotation",
        "status",
        "due_date",
        "created_by",
        "created_at",
    )

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(JobStatusHistory)
class JobStatusHistoryAdmin(SupportScopedReadOnlyAdmin):
    organization_lookup = "job__organization_id"
    support_scope = "delivery"
    list_display = ("job", "previous_status", "status", "actor", "created_at")
    readonly_fields = (
        "job",
        "previous_status",
        "status",
        "actor",
        "created_at",
        "note",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(JobDueDateHistory)
class JobDueDateHistoryAdmin(SupportScopedReadOnlyAdmin):
    organization_lookup = "job__organization_id"
    support_scope = "delivery"
    list_display = ("job", "previous_due_date", "due_date", "actor", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(JobAssignment)
class JobAssignmentAdmin(SupportScopedReadOnlyAdmin):
    organization_lookup = "job__organization_id"
    support_scope = "delivery"
    list_display = ("job", "user", "assigned_by", "assigned_at", "unassigned_at")
    readonly_fields = (
        "job",
        "user",
        "assigned_by",
        "assigned_at",
        "unassigned_by",
        "unassigned_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(JobNote)
class JobNoteAdmin(SupportScopedReadOnlyAdmin):
    organization_lookup = "job__organization_id"
    support_scope = "delivery"
    list_display = ("job", "author", "created_at")
    readonly_fields = ("job", "author", "content", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
