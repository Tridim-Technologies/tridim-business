from rest_framework import serializers

from .models import Customer, CustomerStatusHistory


class CustomerStatusHistorySerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.get_username", read_only=True)

    class Meta:
        model = CustomerStatusHistory
        fields = ("previous_status", "status", "actor", "created_at")


class CustomerSerializer(serializers.ModelSerializer):
    status_history = CustomerStatusHistorySerializer(many=True, read_only=True)

    class Meta:
        model = Customer
        fields = (
            "id",
            "name",
            "contact_name",
            "email",
            "phone",
            "status",
            "status_history",
            "created_at",
        )
        read_only_fields = ("id", "created_at", "status")
