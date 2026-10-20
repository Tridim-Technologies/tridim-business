import hashlib
import json
import uuid
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import ValidationError

from accounts.models import Membership, Organization
from inventory.models import Location, Product, StockMovement

from .models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseReceipt,
    PurchaseReceiptLine,
    Supplier,
)
from .serializers import (
    PurchaseOrderSerializer,
    PurchaseOrderWriteSerializer,
    PurchaseReceiptSerializer,
    PurchaseReceiptWriteSerializer,
    SupplierSerializer,
    SupplierWriteSerializer,
)

READERS = {
    Membership.Role.OWNER,
    Membership.Role.ADMIN,
    Membership.Role.OPERATIONS,
    Membership.Role.SALES,
    Membership.Role.FINANCE,
}
WRITERS = {
    Membership.Role.OWNER,
    Membership.Role.ADMIN,
    Membership.Role.OPERATIONS,
}


def _membership(request, organization_id, *, write=False):
    if not request.user.is_authenticated:
        return None, JsonResponse({"detail": "Authentication required."}, status=401)
    membership = Membership.objects.filter(
        user=request.user, organization_id=organization_id
    ).first()
    if membership is None:
        return None, JsonResponse({"detail": "Organization not found."}, status=404)
    allowed = WRITERS if write else READERS
    if membership.role not in allowed:
        return None, JsonResponse(
            {"detail": "You do not have permission to access purchasing."}, status=403
        )
    return membership, None


def _payload(request, serializer_class, *, partial=False):
    try:
        data = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse({"detail": "Invalid JSON."}, status=400)
    serializer = serializer_class(data=data, partial=partial)
    try:
        serializer.is_valid(raise_exception=True)
    except ValidationError as error:
        return None, JsonResponse(error.detail, status=400)
    return serializer.validated_data, None


def _received_quantities(order_ids):
    rows = (
        PurchaseReceiptLine.objects.filter(order_line__purchase_order_id__in=order_ids)
        .values("order_line_id")
        .annotate(total=Sum("quantity"))
    )
    return {row["order_line_id"]: row["total"] for row in rows}


def _order_response(orders):
    orders = list(orders)
    received = _received_quantities([order.pk for order in orders])
    return PurchaseOrderSerializer(
        orders, many=True, context={"received": received}
    ).data


def _order_queryset(organization_id):
    return (
        PurchaseOrder.objects.filter(organization_id=organization_id)
        .select_related("supplier", "created_by", "issued_by", "cancelled_by")
        .prefetch_related(
            "lines",
            "receipts__location",
            "receipts__actor",
            "receipts__lines__order_line",
            "receipts__lines__stock_movement",
        )
    )


def _create_order_lines(order, lines):
    product_ids = {line["product_id"] for line in lines}
    products = {
        product.pk: product
        for product in Product.objects.filter(
            organization_id=order.organization_id,
            pk__in=product_ids,
            is_active=True,
        )
    }
    if len(products) != len(product_ids):
        return JsonResponse(
            {"lines": ["One or more active products were not found."]}, status=404
        )
    PurchaseOrderLine.objects.bulk_create(
        [
            PurchaseOrderLine(
                purchase_order=order,
                product=products[line["product_id"]],
                product_sku=products[line["product_id"]].sku,
                product_name=products[line["product_id"]].name,
                base_unit=products[line["product_id"]].base_unit,
                ordered_quantity=line["ordered_quantity"],
            )
            for line in lines
        ]
    )
    return None


@require_http_methods(["GET"])
def purchasing_view(request, organization_id):
    _, error = _membership(request, organization_id)
    if error:
        return error
    orders = _order_queryset(organization_id)
    return JsonResponse(
        {
            "suppliers": SupplierSerializer(
                Supplier.objects.filter(organization_id=organization_id), many=True
            ).data,
            "orders": _order_response(orders),
            "locations": list(
                Location.objects.filter(organization_id=organization_id).values(
                    "id", "code", "name", "is_active"
                )
            ),
            "products": list(
                Product.objects.filter(organization_id=organization_id).values(
                    "id", "sku", "name", "base_unit", "is_active"
                )
            ),
        }
    )


@require_http_methods(["POST"])
def suppliers_view(request, organization_id):
    _, error = _membership(request, organization_id, write=True)
    if error:
        return error
    values, error = _payload(request, SupplierWriteSerializer)
    if error:
        return error
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        if Supplier.objects.filter(
            organization_id=organization_id, code__iexact=values["code"]
        ).exists():
            return JsonResponse({"code": ["Supplier code already exists."]}, status=409)
        try:
            supplier = Supplier.objects.create(
                organization_id=organization_id, created_by=request.user, **values
            )
        except IntegrityError:
            return JsonResponse({"code": ["Supplier code already exists."]}, status=409)
    return JsonResponse(SupplierSerializer(supplier).data, status=201)


@require_http_methods(["PATCH"])
def supplier_detail_view(request, organization_id, supplier_id):
    _, error = _membership(request, organization_id, write=True)
    if error:
        return error
    values, error = _payload(request, SupplierWriteSerializer, partial=True)
    if error:
        return error
    if not values:
        return JsonResponse(
            {"detail": "Provide supplier fields to update."}, status=400
        )
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        supplier = (
            Supplier.objects.select_for_update()
            .filter(organization_id=organization_id, pk=supplier_id)
            .first()
        )
        if supplier is None:
            return JsonResponse({"detail": "Supplier not found."}, status=404)
        code = values.get("code", supplier.code)
        if (
            Supplier.objects.filter(organization_id=organization_id, code__iexact=code)
            .exclude(pk=supplier.pk)
            .exists()
        ):
            return JsonResponse({"code": ["Supplier code already exists."]}, status=409)
        for field, value in values.items():
            setattr(supplier, field, value)
        try:
            with transaction.atomic():
                supplier.save(update_fields=[*values, "updated_at"])
        except IntegrityError:
            return JsonResponse({"code": ["Supplier code already exists."]}, status=409)
    return JsonResponse(SupplierSerializer(supplier).data)


@require_http_methods(["POST"])
def purchase_orders_view(request, organization_id):
    _, error = _membership(request, organization_id, write=True)
    if error:
        return error
    values, error = _payload(request, PurchaseOrderWriteSerializer)
    if error:
        return error
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        supplier = Supplier.objects.filter(
            organization_id=organization_id,
            pk=values["supplier_id"],
            is_active=True,
        ).first()
        if supplier is None:
            return JsonResponse({"detail": "Active supplier not found."}, status=404)
        order = PurchaseOrder.objects.create(
            organization_id=organization_id,
            supplier=supplier,
            supplier_code=supplier.code,
            supplier_name=supplier.name,
            note=values.get("note", ""),
            created_by=request.user,
        )
        error = _create_order_lines(order, values["lines"])
        if error:
            transaction.set_rollback(True)
            return error
    order = _order_queryset(organization_id).get(pk=order.pk)
    data = PurchaseOrderSerializer(order, context={"received": {}}).data
    return JsonResponse(data, status=201)


@require_http_methods(["PATCH", "DELETE"])
def purchase_order_detail_view(request, organization_id, order_id):
    _, error = _membership(request, organization_id, write=True)
    if error:
        return error
    values = None
    if request.method == "PATCH":
        values, error = _payload(request, PurchaseOrderWriteSerializer)
        if error:
            return error
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        order = (
            PurchaseOrder.objects.select_for_update()
            .filter(organization_id=organization_id, pk=order_id)
            .first()
        )
        if order is None:
            return JsonResponse({"detail": "Purchase order not found."}, status=404)
        if order.status != PurchaseOrder.Status.DRAFT:
            return JsonResponse(
                {"detail": "Only draft purchase orders can be edited or deleted."},
                status=409,
            )
        if request.method == "DELETE":
            order.delete()
            return JsonResponse({}, status=204)
        supplier = Supplier.objects.filter(
            organization_id=organization_id,
            pk=values["supplier_id"],
            is_active=True,
        ).first()
        if supplier is None:
            return JsonResponse({"detail": "Active supplier not found."}, status=404)
        error = _create_order_lines_preview(organization_id, values["lines"])
        if error:
            return error
        order.supplier = supplier
        order.supplier_code = supplier.code
        order.supplier_name = supplier.name
        order.note = values.get("note", "")
        order.save(
            update_fields=[
                "supplier",
                "supplier_code",
                "supplier_name",
                "note",
                "updated_at",
            ]
        )
        order.lines.all().delete()
        error = _create_order_lines(order, values["lines"])
        if error:
            transaction.set_rollback(True)
            return error
    order = _order_queryset(organization_id).get(pk=order.pk)
    return JsonResponse(PurchaseOrderSerializer(order, context={"received": {}}).data)


def _create_order_lines_preview(organization_id, lines):
    product_ids = {line["product_id"] for line in lines}
    found = Product.objects.filter(
        organization_id=organization_id, pk__in=product_ids, is_active=True
    ).count()
    if found != len(product_ids):
        return JsonResponse(
            {"lines": ["One or more active products were not found."]}, status=404
        )
    return None


@require_http_methods(["POST"])
def purchase_order_issue_view(request, organization_id, order_id):
    _, error = _membership(request, organization_id, write=True)
    if error:
        return error
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        order = (
            PurchaseOrder.objects.select_for_update()
            .filter(organization_id=organization_id, pk=order_id)
            .select_related("supplier")
            .first()
        )
        if order is None:
            return JsonResponse({"detail": "Purchase order not found."}, status=404)
        if order.status in {
            PurchaseOrder.Status.ISSUED,
            PurchaseOrder.Status.PARTIALLY_RECEIVED,
            PurchaseOrder.Status.RECEIVED,
        }:
            order = _order_queryset(organization_id).get(pk=order.pk)
            return JsonResponse(
                PurchaseOrderSerializer(
                    order, context={"received": _received_quantities([order.pk])}
                ).data
            )
        if order.status != PurchaseOrder.Status.DRAFT:
            return JsonResponse(
                {"detail": "Cancelled orders cannot be issued."}, status=409
            )
        if not order.lines.exists():
            return JsonResponse(
                {"detail": "Add at least one line before issuing."}, status=409
            )
        if not order.supplier.is_active:
            return JsonResponse({"detail": "The supplier is inactive."}, status=409)
        if order.lines.filter(product__is_active=False).exists():
            return JsonResponse(
                {"detail": "Activate all ordered products before issuing."}, status=409
            )
        order.status = PurchaseOrder.Status.ISSUED
        order.issued_by = request.user
        order.issued_at = timezone.now()
        order.save(update_fields=["status", "issued_by", "issued_at", "updated_at"])
    order = _order_queryset(organization_id).get(pk=order.pk)
    return JsonResponse(PurchaseOrderSerializer(order, context={"received": {}}).data)


@require_http_methods(["POST"])
def purchase_order_cancel_view(request, organization_id, order_id):
    _, error = _membership(request, organization_id, write=True)
    if error:
        return error
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        order = (
            PurchaseOrder.objects.select_for_update()
            .filter(organization_id=organization_id, pk=order_id)
            .first()
        )
        if order is None:
            return JsonResponse({"detail": "Purchase order not found."}, status=404)
        if order.status == PurchaseOrder.Status.CANCELLED:
            order = _order_queryset(organization_id).get(pk=order.pk)
            return JsonResponse(
                PurchaseOrderSerializer(
                    order, context={"received": _received_quantities([order.pk])}
                ).data
            )
        if order.status not in {
            PurchaseOrder.Status.ISSUED,
            PurchaseOrder.Status.PARTIALLY_RECEIVED,
        }:
            return JsonResponse(
                {
                    "detail": "Only issued or partially received orders can be cancelled."
                },
                status=409,
            )
        order.status = PurchaseOrder.Status.CANCELLED
        order.cancelled_by = request.user
        order.cancelled_at = timezone.now()
        order.save(
            update_fields=["status", "cancelled_by", "cancelled_at", "updated_at"]
        )
    order = _order_queryset(organization_id).get(pk=order.pk)
    return JsonResponse(
        PurchaseOrderSerializer(
            order, context={"received": _received_quantities([order.pk])}
        ).data
    )


def _receipt_signature(order_id, values):
    normalized = {
        "order_id": order_id,
        "location_id": values["location_id"],
        "lines": sorted(
            (
                {
                    "order_line_id": line["order_line_id"],
                    "quantity": format(line["quantity"], ".3f"),
                }
                for line in values["lines"]
            ),
            key=lambda line: line["order_line_id"],
        ),
    }
    return hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@require_http_methods(["GET", "POST"])
def purchase_order_receipts_view(request, organization_id, order_id):
    _, error = _membership(request, organization_id, write=request.method == "POST")
    if error:
        return error
    order = PurchaseOrder.objects.filter(
        organization_id=organization_id, pk=order_id
    ).first()
    if order is None:
        return JsonResponse({"detail": "Purchase order not found."}, status=404)
    if request.method == "GET":
        receipts = (
            PurchaseReceipt.objects.filter(
                organization_id=organization_id, purchase_order=order
            )
            .select_related("purchase_order", "location", "actor")
            .prefetch_related("lines__order_line", "lines__stock_movement")
        )
        return JsonResponse(
            {"results": PurchaseReceiptSerializer(receipts, many=True).data}
        )

    values, error = _payload(request, PurchaseReceiptWriteSerializer)
    if error:
        return error
    signature = _receipt_signature(order.pk, values)
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        existing = PurchaseReceipt.objects.filter(
            organization_id=organization_id,
            idempotency_key=values["idempotency_key"],
        ).first()
        if existing:
            if existing.request_signature != signature:
                return JsonResponse(
                    {"detail": "Idempotency key was used for a different receipt."},
                    status=409,
                )
            receipt = (
                PurchaseReceipt.objects.select_related(
                    "purchase_order", "location", "actor"
                )
                .prefetch_related("lines__order_line", "lines__stock_movement")
                .get(pk=existing.pk)
            )
            data = PurchaseReceiptSerializer(receipt).data
            data["replayed"] = True
            return JsonResponse(data)

        locked_order = (
            PurchaseOrder.objects.select_for_update()
            .filter(organization_id=organization_id, pk=order_id)
            .first()
        )
        if locked_order is None:
            return JsonResponse({"detail": "Purchase order not found."}, status=404)
        if locked_order.status not in {
            PurchaseOrder.Status.ISSUED,
            PurchaseOrder.Status.PARTIALLY_RECEIVED,
        }:
            return JsonResponse(
                {"detail": "Only issued or partially received orders can be received."},
                status=409,
            )
        location = Location.objects.filter(
            organization_id=organization_id,
            pk=values["location_id"],
            is_active=True,
        ).first()
        if location is None:
            return JsonResponse({"detail": "Active location not found."}, status=404)
        requested_line_ids = {line["order_line_id"] for line in values["lines"]}
        order_lines = {
            line.pk: line
            for line in PurchaseOrderLine.objects.select_for_update().filter(
                purchase_order=locked_order, pk__in=requested_line_ids
            )
        }
        if len(order_lines) != len(requested_line_ids):
            return JsonResponse(
                {"lines": ["One or more lines do not belong to this order."]},
                status=404,
            )
        already_received = _received_quantities([locked_order.pk])
        for line in values["lines"]:
            order_line = order_lines[line["order_line_id"]]
            remaining = order_line.ordered_quantity - already_received.get(
                order_line.pk, Decimal("0")
            )
            if line["quantity"] > remaining:
                return JsonResponse(
                    {
                        "lines": [
                            f"Received quantity exceeds the remaining amount for {order_line.product_sku}."
                        ]
                    },
                    status=409,
                )

        receipt = PurchaseReceipt.objects.create(
            organization_id=organization_id,
            purchase_order=locked_order,
            location=location,
            actor=request.user,
            idempotency_key=values["idempotency_key"],
            request_signature=signature,
        )
        for item in values["lines"]:
            order_line = order_lines[item["order_line_id"]]
            receipt_line = PurchaseReceiptLine.objects.create(
                receipt=receipt,
                order_line=order_line,
                quantity=item["quantity"],
            )
            StockMovement.objects.create(
                organization_id=organization_id,
                product=order_line.product,
                kind=StockMovement.Kind.RECEIPT,
                location=location,
                quantity=item["quantity"],
                reason=f"Received against supplier order {locked_order.reference}",
                idempotency_key=uuid.uuid4(),
                actor=request.user,
                source_receipt_line=receipt_line,
            )
        quantities_after = _received_quantities([locked_order.pk])
        if all(
            quantities_after.get(line.pk, Decimal("0")) >= line.ordered_quantity
            for line in locked_order.lines.all()
        ):
            locked_order.status = PurchaseOrder.Status.RECEIVED
        else:
            locked_order.status = PurchaseOrder.Status.PARTIALLY_RECEIVED
        locked_order.save(update_fields=["status", "updated_at"])
    receipt = (
        PurchaseReceipt.objects.select_related("purchase_order", "location", "actor")
        .prefetch_related("lines__order_line", "lines__stock_movement")
        .get(pk=receipt.pk)
    )
    data = PurchaseReceiptSerializer(receipt).data
    data["replayed"] = False
    return JsonResponse(data, status=201)
