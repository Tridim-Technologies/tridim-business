from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.admin.models import CHANGE, LogEntry
from django.utils import timezone

from .models import (
    Membership,
    Organization,
    SupportAccess,
    SupportAccessAuditEvent,
)


# The built-in user and group admins otherwise let an is_staff support user
# inspect or change accounts outside the organization support grant.
UserModel = get_user_model()
ExistingUserAdmin = admin.site._registry[UserModel].__class__
ExistingGroupAdmin = admin.site._registry[Group].__class__
admin.site.unregister(UserModel)
admin.site.unregister(Group)


class SuperuserOnlyAuthAdmin:
    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


admin.site.register(
    UserModel,
    type("RestrictedUserAdmin", (SuperuserOnlyAuthAdmin, ExistingUserAdmin), {}),
)
admin.site.register(
    Group,
    type("RestrictedGroupAdmin", (SuperuserOnlyAuthAdmin, ExistingGroupAdmin), {}),
)


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 1


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)
    inlines = (MembershipInline,)

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("organization", "user", "role", "created_at")
    list_filter = ("role",)
    search_fields = ("organization__name", "user__username", "user__email")

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(SupportAccess)
class SupportAccessAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "organization",
        "scope",
        "purpose",
        "granted_by",
        "granted_at",
        "expires_at",
        "revoked_at",
    )
    list_filter = ("organization", "scope", "revoked_at", "expires_at")
    search_fields = ("user__username", "organization__name", "purpose")
    readonly_fields = ("granted_by", "granted_at", "revoked_at")
    actions = ("revoke_access",)

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if not change:
            obj.granted_by = request.user
            obj.full_clean()
        super().save_model(request, obj, form, change)

    def get_readonly_fields(self, request, obj=None):
        if obj is not None:
            return tuple(field.name for field in self.model._meta.fields)
        return super().get_readonly_fields(request, obj)

    @admin.action(description="Revoke selected support access")
    def revoke_access(self, request, queryset):
        now = timezone.now()
        active = queryset.filter(revoked_at__isnull=True, expires_at__gt=now)
        count = active.count()
        for grant in active:
            grant.revoked_at = now
            grant.save(update_fields=("revoked_at",))
            LogEntry.objects.log_actions(
                user_id=request.user.pk,
                queryset=[grant],
                action_flag=CHANGE,
                change_message="Support access revoked",
                single_object=True,
            )
        self.message_user(request, f"Revoked {count} support access grant(s).")


@admin.register(SupportAccessAuditEvent)
class SupportAccessAuditEventAdmin(admin.ModelAdmin):
    list_display = (
        "accessed_at",
        "support_access",
        "access_type",
        "model_label",
        "object_pk",
    )
    list_filter = ("access_type", "model_label", "accessed_at")
    search_fields = (
        "support_access__user__username",
        "support_access__organization__name",
        "model_label",
        "object_pk",
    )
    readonly_fields = tuple(
        field.name for field in SupportAccessAuditEvent._meta.fields
    )

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
