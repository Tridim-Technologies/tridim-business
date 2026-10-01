from django.contrib import admin

from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "email", "created_at")
    list_filter = ("organization",)
    search_fields = ("name", "contact_name", "email", "phone")
