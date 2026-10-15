from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from accounts.models import Membership
from .models import LeaveRequest, LeaveRequestHistory


class LeaveRequestCreateSerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    category = serializers.ChoiceField(choices=LeaveRequest.Category.choices)
    note = serializers.CharField(max_length=500, allow_blank=True, required=False)

    def validate_start_date(self, value):
        if value < timezone.localdate():
            raise serializers.ValidationError("Start date cannot be in the past.")
        return value

    def validate(self, attrs):
        start_date = attrs["start_date"]
        end_date = attrs["end_date"]
        if end_date < start_date:
            raise serializers.ValidationError(
                {"end_date": "End date must be on or after the start date."}
            )
        if end_date - start_date > timedelta(days=366):
            raise serializers.ValidationError(
                {"end_date": "A leave request cannot exceed 367 inclusive days."}
            )
        attrs["note"] = " ".join(attrs.get("note", "").split())
        return attrs


class LeaveRequestHistorySerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.get_username", read_only=True)

    class Meta:
        model = LeaveRequestHistory
        fields = ("action", "actor", "reason", "created_at")


class LeaveRequestSerializer(serializers.ModelSerializer):
    employee = serializers.CharField(
        source="membership.user.get_username", read_only=True
    )
    reviewed_by = serializers.CharField(
        source="reviewed_by.get_username", read_only=True, allow_null=True
    )
    history = LeaveRequestHistorySerializer(many=True, read_only=True)
    is_requester = serializers.SerializerMethodField()

    def get_is_requester(self, instance):
        request = self.context.get("request")
        return bool(request and instance.membership.user_id == request.user.id)

    class Meta:
        model = LeaveRequest
        fields = (
            "id",
            "employee",
            "is_requester",
            "start_date",
            "end_date",
            "category",
            "note",
            "status",
            "reviewed_by",
            "reviewed_at",
            "decision_reason",
            "created_at",
            "history",
        )


def membership_can_manage_leave(membership):
    return membership.role in {
        Membership.Role.OWNER,
        Membership.Role.ADMIN,
        Membership.Role.OPERATIONS,
    }
