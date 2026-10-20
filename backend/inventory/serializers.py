from decimal import Decimal

from rest_framework import serializers

from .models import Location, Product, StockMovement


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


class ProductWriteSerializer(StrictSerializer):
    sku = serializers.RegexField(regex=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    name = serializers.CharField(max_length=160, min_length=2, trim_whitespace=True)
    base_unit = serializers.RegexField(regex=r"^[A-Za-z0-9._-]{1,16}$")
    is_active = serializers.BooleanField(required=False)

    def validate_sku(self, value):
        return value.strip().upper()


class LocationWriteSerializer(StrictSerializer):
    code = serializers.RegexField(regex=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
    name = serializers.CharField(max_length=120, min_length=2, trim_whitespace=True)
    is_active = serializers.BooleanField(required=False)

    def validate_code(self, value):
        return value.strip().upper()


class MovementWriteSerializer(StrictSerializer):
    product_id = serializers.IntegerField(min_value=1)
    kind = serializers.ChoiceField(choices=StockMovement.Kind.choices)
    location_id = serializers.IntegerField(min_value=1)
    destination_id = serializers.IntegerField(min_value=1, required=False)
    direction = serializers.ChoiceField(
        choices=StockMovement.Direction.choices, required=False
    )
    quantity = serializers.DecimalField(
        max_digits=18,
        decimal_places=3,
        min_value=Decimal("0.001"),
    )
    reason = serializers.CharField(max_length=500, min_length=3, trim_whitespace=True)
    idempotency_key = serializers.UUIDField()

    def validate_quantity(self, value):
        if isinstance(self.initial_data.get("quantity"), float):
            raise serializers.ValidationError(
                "Send quantity as an exact decimal string."
            )
        return value

    def validate(self, attrs):
        kind = attrs["kind"]
        destination = attrs.get("destination_id")
        direction = attrs.get("direction")
        if kind == StockMovement.Kind.TRANSFER:
            if destination is None:
                raise serializers.ValidationError(
                    {"destination_id": "A destination is required for transfers."}
                )
            if destination == attrs["location_id"]:
                raise serializers.ValidationError(
                    {"destination_id": "Source and destination must differ."}
                )
            if direction:
                raise serializers.ValidationError(
                    {"direction": "Direction is not used for transfers."}
                )
        elif kind == StockMovement.Kind.ADJUSTMENT:
            if not direction:
                raise serializers.ValidationError(
                    {"direction": "Choose increase or decrease for an adjustment."}
                )
            if destination is not None:
                raise serializers.ValidationError(
                    {"destination_id": "Adjustments use one location."}
                )
        elif destination is not None or direction:
            raise serializers.ValidationError(
                "Receipts and issues do not accept a destination or direction."
            )
        return attrs


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ("id", "sku", "name", "base_unit", "is_active", "created_at")
        read_only_fields = fields


class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = ("id", "code", "name", "is_active", "created_at")
        read_only_fields = fields


class StockMovementSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.get_username", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    destination_code = serializers.CharField(
        source="destination.code", read_only=True, allow_null=True
    )
    supplier_order_reference = serializers.CharField(
        source="source_receipt_line.receipt.purchase_order.reference",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = StockMovement
        fields = (
            "id",
            "product_id",
            "product_sku",
            "product_name",
            "kind",
            "location_id",
            "location_code",
            "destination_id",
            "destination_code",
            "supplier_order_reference",
            "direction",
            "quantity",
            "reason",
            "idempotency_key",
            "actor",
            "created_at",
        )
        read_only_fields = fields
