from rest_framework import serializers

from accounts.models import Membership
from .models import EmployeeProfile


class EmployeeProfileSerializer(serializers.ModelSerializer):
    membership_id = serializers.PrimaryKeyRelatedField(
        source="membership",
        queryset=Membership.objects.none(),
        write_only=True,
        required=True,
    )
    username = serializers.CharField(
        source="membership.user.get_username", read_only=True
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        organization_id = self.context.get("organization_id")
        if organization_id is not None:
            self.fields["membership_id"].queryset = Membership.objects.filter(
                organization_id=organization_id, user__is_active=True
            )

    class Meta:
        model = EmployeeProfile
        fields = (
            "id",
            "membership_id",
            "username",
            "display_name",
            "job_title",
            "department",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        if not self.context.get("include_account_username", False):
            representation.pop("username", None)
        return representation

    def validate_display_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("A display name is required.")
        return value

    def validate_job_title(self, value):
        return " ".join(value.split())

    def validate_department(self, value):
        return " ".join(value.split())

    def validate(self, attrs):
        if self.instance is not None and "membership" in attrs:
            raise serializers.ValidationError(
                {"membership_id": "An employee profile cannot be reassigned."}
            )
        return attrs
