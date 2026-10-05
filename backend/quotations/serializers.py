from decimal import Decimal

from rest_framework import serializers

from .models import Quotation, QuotationLine, QuotationStatusHistory


class QuotationLineInputSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=240)
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=3, min_value=Decimal("0.001")
    )
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)


class QuotationCreateSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField()
    currency = serializers.RegexField(r"^[A-Za-z]{3}$")
    valid_until = serializers.DateField()
    lines = QuotationLineInputSerializer(many=True, allow_empty=False)


class QuotationLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuotationLine
        fields = ("id", "description", "quantity", "unit_price", "position")


class QuotationStatusHistorySerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.get_username", read_only=True)

    class Meta:
        model = QuotationStatusHistory
        fields = ("previous_status", "status", "actor", "created_at", "note")


class QuotationSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    lines = QuotationLineSerializer(many=True, read_only=True)
    status_history = QuotationStatusHistorySerializer(many=True, read_only=True)
    job_id = serializers.IntegerField(source="job.pk", read_only=True, allow_null=True)

    class Meta:
        model = Quotation
        fields = (
            "id",
            "customer",
            "customer_name",
            "currency",
            "valid_until",
            "status",
            "lines",
            "status_history",
            "job_id",
            "created_at",
            "updated_at",
        )
