from decimal import Decimal

from rest_framework import serializers

from .models import Invoice, InvoiceLine, Payment, PaymentAllocation


class InvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = ("description", "quantity", "unit_price", "line_total", "position")


class InvoiceSerializer(serializers.ModelSerializer):
    job_id = serializers.IntegerField(read_only=True)
    customer_id = serializers.IntegerField(read_only=True)
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
            "customer_id",
            "source_quotation_id",
            "status",
            "issue_date",
            "due_date",
            "currency",
            "total",
            "allocated_total",
            "outstanding_total",
            "payment_state",
            "issued_by",
            "issued_at",
            "correction_reason",
            "void_reason",
            "voided_by",
            "voided_at",
            "replaces_invoice_number",
            "lines",
        )

    allocated_total = serializers.SerializerMethodField()
    outstanding_total = serializers.SerializerMethodField()
    payment_state = serializers.SerializerMethodField()

    @staticmethod
    def _allocated(invoice):
        return sum(
            (
                allocation.amount
                for allocation in invoice.payment_allocations.all()
                if allocation.reversed_at is None
                and allocation.payment.reversed_at is None
            ),
            Decimal("0.00000"),
        )

    def get_allocated_total(self, invoice):
        return self._allocated(invoice)

    def get_outstanding_total(self, invoice):
        return invoice.total - self._allocated(invoice)

    def get_payment_state(self, invoice):
        if invoice.status == Invoice.Status.VOID:
            return "void"
        allocated = self._allocated(invoice)
        if invoice.total - allocated <= 0:
            return "paid"
        return "partial" if allocated > 0 else "unpaid"


class PaymentAllocationSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(
        source="invoice.invoice_number", read_only=True
    )

    class Meta:
        model = PaymentAllocation
        fields = (
            "id",
            "invoice",
            "invoice_number",
            "amount",
            "allocated_by",
            "allocated_at",
            "reversed_by",
            "reversed_at",
            "reversal_reason",
        )
        read_only_fields = fields


class PaymentSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(read_only=True)
    recorded_by = serializers.CharField(
        source="recorded_by.get_username", read_only=True
    )
    reversed_by = serializers.CharField(
        source="reversed_by.get_username", read_only=True, allow_null=True
    )
    allocated_total = serializers.SerializerMethodField()
    unapplied_total = serializers.SerializerMethodField()
    allocations = PaymentAllocationSerializer(many=True, read_only=True)

    class Meta:
        model = Payment
        fields = (
            "id",
            "customer",
            "customer_name",
            "received_date",
            "amount",
            "currency",
            "method",
            "reference",
            "recorded_by",
            "recorded_at",
            "allocated_total",
            "unapplied_total",
            "reversed_by",
            "reversed_at",
            "reversal_reason",
            "allocations",
        )

    @staticmethod
    def _allocated(payment):
        if payment.reversed_at is not None:
            return Decimal("0.00000")
        return sum(
            (
                allocation.amount
                for allocation in payment.allocations.all()
                if allocation.reversed_at is None
            ),
            Decimal("0.00000"),
        )

    def get_allocated_total(self, payment):
        return self._allocated(payment)

    def get_unapplied_total(self, payment):
        if payment.reversed_at is not None:
            return Decimal("0.00000")
        return payment.amount - self._allocated(payment)


class PaymentRecordSerializer(serializers.Serializer):
    customer = serializers.IntegerField(min_value=1)
    received_date = serializers.DateField()
    amount = serializers.DecimalField(
        max_digits=30, decimal_places=5, min_value=Decimal("0.00001")
    )
    currency = serializers.RegexField(r"^[A-Z]{3}$")
    method = serializers.ChoiceField(choices=Payment.Method.choices)
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True)


class PaymentAllocateSerializer(serializers.Serializer):
    invoice = serializers.UUIDField()
    amount = serializers.DecimalField(
        max_digits=30, decimal_places=5, min_value=Decimal("0.00001")
    )


class ReversalSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=240, trim_whitespace=True)

    def validate_reason(self, value):
        if not value:
            raise serializers.ValidationError("A reason is required.")
        return value


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
