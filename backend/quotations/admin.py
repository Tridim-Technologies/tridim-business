from django.contrib import admin

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


class QuotationLineInline(admin.TabularInline):
    model = QuotationLine
    extra = 0


class QuotationStatusHistoryInline(admin.TabularInline):
    model = QuotationStatusHistory
    extra = 0
    can_delete = False
    readonly_fields = ("previous_status", "status", "actor", "created_at", "note")


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "organization", "status", "valid_until")
    list_filter = ("organization", "status", "currency")
    search_fields = ("customer__name", "id")
    inlines = (QuotationLineInline, QuotationStatusHistoryInline)


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
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
class JobStatusHistoryAdmin(admin.ModelAdmin):
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
class JobDueDateHistoryAdmin(admin.ModelAdmin):
    list_display = ("job", "previous_due_date", "due_date", "actor", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(JobAssignment)
class JobAssignmentAdmin(admin.ModelAdmin):
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
class JobNoteAdmin(admin.ModelAdmin):
    list_display = ("job", "author", "created_at")
    readonly_fields = ("job", "author", "content", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
