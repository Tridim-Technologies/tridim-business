from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from .models import ExpenseClaim, ExpenseClaimHistory


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("Expected a JSON object.")
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {field: "This field is not accepted." for field in sorted(unknown)}
            )
        return super().to_internal_value(data)


class ExpenseClaimWriteSerializer(StrictSerializer):
    job_id = serializers.IntegerField(min_value=1, required=False)
    revision = serializers.IntegerField(min_value=1, required=False)
    expense_date = serializers.DateField()
    amount = serializers.DecimalField(
        max_digits=18, decimal_places=5, min_value=Decimal("0.00001")
    )
    currency = serializers.RegexField(regex=r"^[A-Z]{3}$")
    category = serializers.ChoiceField(choices=ExpenseClaim.Category.choices)
    merchant = serializers.CharField(max_length=160, required=False, allow_blank=True)
    purpose = serializers.CharField(max_length=1000, min_length=3, trim_whitespace=True)
    missing_receipt_explanation = serializers.CharField(
        max_length=500, required=False, allow_blank=True, trim_whitespace=True
    )

    def validate_expense_date(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError("Expense date cannot be in the future.")
        return value

    def validate_amount(self, value):
        if isinstance(self.initial_data.get("amount"), float):
            raise serializers.ValidationError(
                "Send the amount as an exact decimal string."
            )
        return value


class ExpenseClaimTransitionSerializer(StrictSerializer):
    action = serializers.ChoiceField(
        choices=(
            "submit",
            "return",
            "resubmit",
            "waive",
            "approve",
            "reject",
            "withdraw",
        )
    )
    revision = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(
        max_length=500, required=False, allow_blank=True, trim_whitespace=True
    )

    def validate(self, attrs):
        action = attrs["action"]
        if action in {"return", "waive", "reject"} and not attrs.get("reason"):
            raise serializers.ValidationError(
                {"reason": f"A reason is required to {action} a claim."}
            )
        return attrs


class ExpenseClaimHistorySerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.get_username", read_only=True)

    class Meta:
        model = ExpenseClaimHistory
        fields = (
            "action",
            "previous_status",
            "status",
            "actor",
            "version",
            "revision",
            "expense_date",
            "amount",
            "currency",
            "category",
            "merchant",
            "purpose",
            "missing_receipt_explanation",
            "reason",
            "created_at",
        )


class ExpenseClaimSerializer(serializers.ModelSerializer):
    claimant = serializers.CharField(source="claimant.get_username", read_only=True)
    history = ExpenseClaimHistorySerializer(many=True, read_only=True)
    receipt_state = serializers.SerializerMethodField()

    class Meta:
        model = ExpenseClaim
        fields = (
            "id",
            "job_id",
            "claimant",
            "expense_date",
            "amount",
            "currency",
            "category",
            "merchant",
            "purpose",
            "missing_receipt_explanation",
            "receipt_state",
            "status",
            "version",
            "revision",
            "approved_at",
            "created_at",
            "updated_at",
            "history",
        )
        read_only_fields = fields

    def get_receipt_state(self, obj):
        return "waived" if obj.waived_version == obj.version else "missing"


class ExpenseClaimFinanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseClaim
        fields = (
            "id",
            "job_id",
            "expense_date",
            "amount",
            "currency",
            "category",
            "status",
            "approved_at",
        )
        read_only_fields = fields
