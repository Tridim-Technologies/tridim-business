from django.contrib import admin

from .models import Job, Quotation, QuotationLine, QuotationStatusHistory


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
