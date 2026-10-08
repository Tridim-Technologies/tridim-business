from django.contrib import admin

from .models import SupportAccess, SupportAccessAuditEvent


class SupportReadOnlyTabularInline(admin.TabularInline):
    support_scope = None

    def has_add_permission(self, request, obj=None):
        if request.user.is_superuser:
            return super().has_add_permission(request, obj)
        return False

    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser:
            return super().has_change_permission(request, obj)
        return False

    def has_view_permission(self, request, obj=None):
        if request.user.is_superuser:
            return super().has_view_permission(request, obj)
        if not request.user.is_staff or not self.support_scope:
            return False
        grants = SupportAccess.active_for(request.user).filter(scope=self.support_scope)
        if obj is not None:
            organization_id = getattr(obj, "organization_id", None)
            return bool(
                organization_id
                and grants.filter(organization_id=organization_id).exists()
            )
        # The inline formset itself binds this queryset to the authorized parent.
        return grants.exists()

    def has_delete_permission(self, request, obj=None):
        if request.user.is_superuser:
            return super().has_delete_permission(request, obj)
        return False

    def get_readonly_fields(self, request, obj=None):
        if request.user.is_superuser:
            return super().get_readonly_fields(request, obj)
        return tuple(field.name for field in self.model._meta.fields)


class SupportScopedReadOnlyAdmin(admin.ModelAdmin):
    """Expose tenant records to support staff only under active org grants."""

    organization_lookup = None
    support_scope = None

    def _active_grants(self, request):
        if not self.support_scope:
            return SupportAccess.objects.none()
        return (
            SupportAccess.active_for(request.user)
            .filter(scope=self.support_scope)
            .select_related("organization")
        )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        if not request.user.is_staff or not self.organization_lookup:
            return queryset.none()
        return queryset.filter(
            **{
                f"{self.organization_lookup}__in": self._active_grants(request).values(
                    "organization_id"
                )
            }
        )

    def has_module_permission(self, request):
        if request.user.is_superuser:
            return super().has_module_permission(request)
        return (
            request.user.is_staff
            and bool(self.organization_lookup)
            and self._active_grants(request).exists()
        )

    def get_model_perms(self, request):
        if request.user.is_superuser:
            return super().get_model_perms(request)
        if self.has_module_permission(request):
            return {"view": True}
        return {}

    def has_view_permission(self, request, obj=None):
        if request.user.is_superuser:
            return super().has_view_permission(request, obj)
        if not self.has_module_permission(request):
            return False
        return obj is None or self.get_queryset(request).filter(pk=obj.pk).exists()

    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser:
            return super().has_change_permission(request, obj)
        return False

    def has_add_permission(self, request):
        if request.user.is_superuser:
            return super().has_add_permission(request)
        return False

    def has_delete_permission(self, request, obj=None):
        if request.user.is_superuser:
            return super().has_delete_permission(request, obj)
        return False

    def get_readonly_fields(self, request, obj=None):
        if request.user.is_superuser:
            return super().get_readonly_fields(request, obj)
        return tuple(field.name for field in self.model._meta.fields)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.clear()
        return actions

    def get_list_filter(self, request):
        list_filter = super().get_list_filter(request)
        if request.user.is_superuser:
            return list_filter
        return tuple(
            item
            for item in list_filter
            if not (
                isinstance((field := item[0] if isinstance(item, tuple) else item), str)
                and field.split("__", 1)[0] == "organization"
            )
        )

    def get_inline_instances(self, request, obj=None):
        return super().get_inline_instances(request, obj)

    def _audit_access(self, request, obj=None):
        if request.user.is_superuser or not request.user.is_staff:
            return
        access_type = (
            SupportAccessAuditEvent.AccessType.OBJECT
            if obj is not None
            else SupportAccessAuditEvent.AccessType.LIST
        )
        grants = self._active_grants(request)
        if obj is not None:
            organization_id = (
                self.get_queryset(request)
                .filter(pk=obj.pk)
                .values_list(self.organization_lookup, flat=True)
                .first()
            )
            grants = grants.filter(organization_id=organization_id)
        SupportAccessAuditEvent.objects.bulk_create(
            [
                SupportAccessAuditEvent(
                    support_access=grant,
                    model_label=self.model._meta.label_lower,
                    object_pk=str(obj.pk) if obj is not None else "",
                    access_type=access_type,
                )
                for grant in grants
            ]
        )

    def changelist_view(self, request, extra_context=None):
        self._audit_access(request)
        return super().changelist_view(request, extra_context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        obj = self.get_queryset(request).filter(pk=object_id).first()
        if obj is not None and request.method in {"GET", "HEAD"}:
            self._audit_access(request, obj)
        return super().change_view(request, object_id, form_url, extra_context)
