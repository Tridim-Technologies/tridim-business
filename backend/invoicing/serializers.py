from decimal import Decimal

from rest_framework import serializers

from .models import Invoice, InvoiceLine


class InvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = ("description", "quantity", "unit_price", "line_total", "position")


class InvoiceSerializer(serializers.ModelSerializer):
    job_id = serializers.IntegerField(read_only=True)
    replaces_invoice_number = serializers.CharField(
        source="replaces.invoice_number", read_only=True, allow_null=True
    )
    issued_by = serializers.CharField(source="issued_by.get_username", read_only=True)
    voided_by = serializers.CharField(
        source="voided_by.get_username", read_only=True, allow_null=True
    )
    lines = InvoiceLineSerializer(many=True, read_only=True)

    class Meta:
        model = Invoice
        fields = (
            "id",
            "invoice_number",
            "job_id",
            "customer_name",
            "source_quotation_id",
            "status",
            "issue_date",
            "due_date",
            "currency",
            "total",
            "issued_by",
            "issued_at",
            "correction_reason",
            "void_reason",
            "voided_by",
            "voided_at",
            "replaces_invoice_number",
            "lines",
        )


class InvoiceLineCorrectionSerializer(serializers.Serializer):
    position = serializers.IntegerField(min_value=0)
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=3, min_value=Decimal("0.001")
    )
    unit_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0")
    )


class InvoiceIssueSerializer(serializers.Serializer):
    due_date = serializers.DateField()
    correction_reason = serializers.CharField(
        max_length=240, required=False, allow_blank=True, trim_whitespace=True
    )
    lines = InvoiceLineCorrectionSerializer(
        many=True, required=False, allow_empty=False
    )

    def validate(self, attrs):
        if "lines" in attrs and not attrs.get("correction_reason"):
            raise serializers.ValidationError(
                {"correction_reason": "A reason is required for line corrections."}
            )
        return attrs


class InvoiceVoidSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=240, trim_whitespace=True)

    def validate_reason(self, value):
        if not value:
            raise serializers.ValidationError(
                "A reason is required to void an invoice."
            )
        return value
