from decimal import Decimal

from rest_framework import serializers

from .models import PurchaseOrder, PurchaseReceipt, Supplier


def _quantity(value):
    return format(value.quantize(Decimal("0.001")), "f")


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


class ExactDecimalField(serializers.DecimalField):
    def to_internal_value(self, data):
        if isinstance(data, float):
            raise serializers.ValidationError(
                "Send quantity as an exact decimal string."
            )
        return super().to_internal_value(data)


class SupplierWriteSerializer(StrictSerializer):
    code = serializers.RegexField(regex=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
    name = serializers.CharField(max_length=160, min_length=2, trim_whitespace=True)
    is_active = serializers.BooleanField(required=False)

    def validate_code(self, value):
        return value.strip().upper()


class OrderLineWriteSerializer(StrictSerializer):
    product_id = serializers.IntegerField(min_value=1)
    ordered_quantity = ExactDecimalField(
        max_digits=18,
        decimal_places=3,
        min_value=Decimal("0.001"),
    )


class PurchaseOrderWriteSerializer(StrictSerializer):
    supplier_id = serializers.IntegerField(min_value=1)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True)
    lines = OrderLineWriteSerializer(many=True, min_length=1, max_length=100)

    def validate_lines(self, lines):
        product_ids = [line["product_id"] for line in lines]
        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError(
                "Use one line per product; duplicate product lines are not allowed."
            )
        return lines


class ReceiptLineWriteSerializer(StrictSerializer):
    order_line_id = serializers.IntegerField(min_value=1)
    quantity = ExactDecimalField(
        max_digits=18,
        decimal_places=3,
        min_value=Decimal("0.001"),
    )


class PurchaseReceiptWriteSerializer(StrictSerializer):
    location_id = serializers.IntegerField(min_value=1)
    idempotency_key = serializers.UUIDField()
    lines = ReceiptLineWriteSerializer(many=True, min_length=1, max_length=100)

    def validate_lines(self, lines):
        line_ids = [line["order_line_id"] for line in lines]
        if len(line_ids) != len(set(line_ids)):
            raise serializers.ValidationError(
                "Use one received quantity per order line."
            )
        return lines


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ("id", "code", "name", "is_active", "created_at", "updated_at")


class PurchaseOrderSerializer(serializers.ModelSerializer):
    supplier_code = serializers.CharField(read_only=True)
    supplier_name = serializers.CharField(read_only=True)
    created_by = serializers.CharField(source="created_by.get_username", read_only=True)
    issued_by = serializers.CharField(
        source="issued_by.get_username", read_only=True, allow_null=True
    )
    cancelled_by = serializers.CharField(
        source="cancelled_by.get_username", read_only=True, allow_null=True
    )
    lines = serializers.SerializerMethodField()
    received_lines_count = serializers.SerializerMethodField()
    receipts = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = (
            "id",
            "reference",
            "supplier_id",
            "supplier_code",
            "supplier_name",
            "status",
            "note",
            "created_by",
            "created_at",
            "updated_at",
            "issued_by",
            "issued_at",
            "cancelled_by",
            "cancelled_at",
            "lines",
            "received_lines_count",
            "receipts",
        )

    def get_lines(self, order):
        received = self.context.get("received", {})
        return [
            {
                "id": line.id,
                "product_id": line.product_id,
                "product_sku": line.product_sku,
                "product_name": line.product_name,
                "base_unit": line.base_unit,
                "ordered_quantity": _quantity(line.ordered_quantity),
                "received_quantity": _quantity(received.get(line.id, Decimal("0"))),
                "remaining_quantity": _quantity(
                    line.ordered_quantity - received.get(line.id, Decimal("0"))
                ),
            }
            for line in order.lines.all()
        ]

    def get_received_lines_count(self, order):
        received = self.context.get("received", {})
        return sum(1 for line in order.lines.all() if received.get(line.id, 0) > 0)

    def get_receipts(self, order):
        return PurchaseReceiptSerializer(order.receipts.all(), many=True).data


class PurchaseReceiptSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.get_username", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    lines = serializers.SerializerMethodField()
    replayed = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = PurchaseReceipt
        fields = (
            "id",
            "purchase_order_id",
            "location_id",
            "location_code",
            "actor",
            "idempotency_key",
            "created_at",
            "lines",
            "replayed",
        )

    def get_lines(self, receipt):
        return [
            {
                "order_line_id": line.order_line_id,
                "product_sku": line.order_line.product_sku,
                "product_name": line.order_line.product_name,
                "quantity": _quantity(line.quantity),
                "movement_id": line.stock_movement.id,
            }
            for line in receipt.lines.select_related(
                "order_line", "stock_movement"
            ).all()
        ]
