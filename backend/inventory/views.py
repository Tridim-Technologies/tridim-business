import hashlib
import json
import uuid
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import ValidationError

from accounts.models import Membership, Organization
from quotations.models import Job

from .models import (
    JobMaterialIssue,
    JobMaterialIssueLine,
    Location,
    Product,
    StockMovement,
)
from .serializers import (
    LocationSerializer,
    LocationWriteSerializer,
    JobMaterialIssueSerializer,
    JobMaterialIssueWriteSerializer,
    MovementWriteSerializer,
    ProductSerializer,
    ProductWriteSerializer,
    StockMovementSerializer,
)
from .services import location_stock_balances

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
            {"detail": "You do not have permission to access inventory."}, status=403
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


@require_http_methods(["GET"])
def inventory_view(request, organization_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error
    products = Product.objects.filter(organization_id=organization_id)
    locations = Location.objects.filter(organization_id=organization_id)
    totals = location_stock_balances(organization_id)
    product_data = ProductSerializer(products, many=True).data
    location_data = LocationSerializer(locations, many=True).data
    for product in product_data:
        product["balances"] = [
            {
                "location_id": location["id"],
                "location_code": location["code"],
                "quantity": format(
                    totals.get((product["id"], location["id"]), Decimal("0")), "f"
                ),
            }
            for location in location_data
        ]
        product["on_hand_quantity"] = format(
            sum(
                (Decimal(balance["quantity"]) for balance in product["balances"]),
                Decimal("0.000"),
            ),
            ".3f",
        )
    movements = StockMovement.objects.filter(
        organization_id=organization_id
    ).select_related(
        "product",
        "location",
        "destination",
        "actor",
        "source_receipt_line__receipt__purchase_order",
        "source_job_material_issue_line__issue__job",
    )[:100]
    return JsonResponse(
        {
            "products": product_data,
            "locations": location_data,
            "movements": StockMovementSerializer(movements, many=True).data,
        }
    )


@require_http_methods(["POST"])
def inventory_products_view(request, organization_id):
    _, error = _membership(request, organization_id, write=True)
    if error:
        return error
    values, error = _payload(request, ProductWriteSerializer)
    if error:
        return error
    if Product.objects.filter(
        organization_id=organization_id, sku__iexact=values["sku"]
    ).exists():
        return JsonResponse(
            {"sku": ["SKU already exists in this organization."]}, status=409
        )
    try:
        product = Product.objects.create(
            organization_id=organization_id, created_by=request.user, **values
        )
    except IntegrityError:
        return JsonResponse(
            {"sku": ["SKU already exists in this organization."]}, status=409
        )
    return JsonResponse(ProductSerializer(product).data, status=201)


@require_http_methods(["PATCH"])
def inventory_product_detail_view(request, organization_id, product_id):
    _, error = _membership(request, organization_id, write=True)
    if error:
        return error
    values, error = _payload(request, ProductWriteSerializer, partial=True)
    if error:
        return error
    if not values:
        return JsonResponse({"detail": "Provide product fields to update."}, status=400)
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        product = (
            Product.objects.select_for_update()
            .filter(organization_id=organization_id, pk=product_id)
            .first()
        )
        if product is None:
            return JsonResponse({"detail": "Product not found."}, status=404)
        if (
            "sku" in values
            and Product.objects.filter(
                organization_id=organization_id, sku__iexact=values["sku"]
            )
            .exclude(pk=product.pk)
            .exists()
        ):
            return JsonResponse(
                {"sku": ["SKU already exists in this organization."]}, status=409
            )
        if (
            "base_unit" in values
            and values["base_unit"] != product.base_unit
            and (
                product.stock_movements.exists()
                or product.purchase_order_lines.exists()
            )
        ):
            return JsonResponse(
                {
                    "base_unit": [
                        "A product's unit cannot change after stock movements or supplier order lines exist."
                    ]
                },
                status=409,
            )
        for name, value in values.items():
            setattr(product, name, value)
        try:
            with transaction.atomic():
                product.save(update_fields=[*values, "updated_at"])
        except IntegrityError:
            return JsonResponse(
                {"sku": ["SKU already exists in this organization."]}, status=409
            )
    return JsonResponse(ProductSerializer(product).data)


@require_http_methods(["POST"])
def inventory_locations_view(request, organization_id):
    _, error = _membership(request, organization_id, write=True)
    if error:
        return error
    values, error = _payload(request, LocationWriteSerializer)
    if error:
        return error
    if Location.objects.filter(
        organization_id=organization_id, code__iexact=values["code"]
    ).exists():
        return JsonResponse({"code": ["Location code already exists."]}, status=409)
    try:
        location = Location.objects.create(
            organization_id=organization_id, created_by=request.user, **values
        )
    except IntegrityError:
        return JsonResponse({"code": ["Location code already exists."]}, status=409)
    return JsonResponse(LocationSerializer(location).data, status=201)


@require_http_methods(["PATCH"])
def inventory_location_detail_view(request, organization_id, location_id):
    _, error = _membership(request, organization_id, write=True)
    if error:
        return error
    values, error = _payload(request, LocationWriteSerializer, partial=True)
    if error:
        return error
    if not values:
        return JsonResponse(
            {"detail": "Provide location fields to update."}, status=400
        )
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        location = (
            Location.objects.select_for_update()
            .filter(organization_id=organization_id, pk=location_id)
            .first()
        )
        if location is None:
            return JsonResponse({"detail": "Location not found."}, status=404)
        duplicate = (
            Location.objects.filter(
                organization_id=organization_id,
                code__iexact=values.get("code", location.code),
            )
            .exclude(pk=location.pk)
            .exists()
        )
        if duplicate:
            return JsonResponse({"code": ["Location code already exists."]}, status=409)
        if values.get("is_active") is False and location.is_active:
            has_stock = any(
                balance_location_id == location.pk and quantity > 0
                for (_, balance_location_id), quantity in location_stock_balances(
                    organization_id
                ).items()
            )
            if has_stock:
                return JsonResponse(
                    {"detail": "A location with stock on hand cannot be deactivated."},
                    status=409,
                )
        for name, value in values.items():
            setattr(location, name, value)
        try:
            with transaction.atomic():
                location.save(update_fields=[*values])
        except IntegrityError:
            return JsonResponse({"code": ["Location code already exists."]}, status=409)
    return JsonResponse(LocationSerializer(location).data)


def _same_request(movement, values):
    expected = {
        "product_id": movement.product_id,
        "kind": movement.kind,
        "location_id": movement.location_id,
        "destination_id": movement.destination_id,
        "direction": movement.direction or None,
        "quantity": movement.quantity,
        "reason": movement.reason,
    }
    actual = {key: values.get(key) for key in expected}
    return actual == expected


def _balance(product, location_id):
    movements = StockMovement.objects.filter(
        organization_id=product.organization_id, product=product
    )
    incoming = movements.filter(
        Q(kind=StockMovement.Kind.RECEIPT, location_id=location_id)
        | Q(
            kind=StockMovement.Kind.ADJUSTMENT,
            location_id=location_id,
            direction=StockMovement.Direction.INCREASE,
        )
        | Q(kind=StockMovement.Kind.TRANSFER, destination_id=location_id)
    ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
    outgoing = movements.filter(
        Q(kind=StockMovement.Kind.ISSUE, location_id=location_id)
        | Q(
            kind=StockMovement.Kind.ADJUSTMENT,
            location_id=location_id,
            direction=StockMovement.Direction.DECREASE,
        )
        | Q(kind=StockMovement.Kind.TRANSFER, location_id=location_id)
    ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
    return incoming - outgoing


@require_http_methods(["GET", "POST"])
def inventory_movements_view(request, organization_id):
    membership, error = _membership(
        request, organization_id, write=request.method == "POST"
    )
    if error:
        return error
    if request.method == "GET":
        movements = StockMovement.objects.filter(
            organization_id=organization_id
        ).select_related(
            "product",
            "location",
            "destination",
            "actor",
            "source_receipt_line__receipt__purchase_order",
            "source_job_material_issue_line__issue__job",
        )[:100]
        return JsonResponse(
            {"results": StockMovementSerializer(movements, many=True).data}
        )

    values, error = _payload(request, MovementWriteSerializer)
    if error:
        return error
    with transaction.atomic():
        # Serialize a tenant's movements so retries using one request key cannot race.
        Organization.objects.select_for_update().get(pk=organization_id)
        existing = StockMovement.objects.filter(
            organization_id=organization_id,
            idempotency_key=values["idempotency_key"],
        ).first()
        if existing:
            if not _same_request(existing, values):
                return JsonResponse(
                    {
                        "detail": "Idempotency key was already used for another movement."
                    },
                    status=409,
                )
            data = StockMovementSerializer(existing).data
            data["replayed"] = True
            return JsonResponse(data)

        product = (
            Product.objects.select_for_update()
            .filter(
                organization_id=organization_id,
                pk=values["product_id"],
                is_active=True,
            )
            .first()
        )
        if product is None:
            return JsonResponse({"detail": "Active product not found."}, status=404)
        location = Location.objects.filter(
            organization_id=organization_id,
            pk=values["location_id"],
            is_active=True,
        ).first()
        if location is None:
            return JsonResponse({"detail": "Active location not found."}, status=404)
        destination = None
        if values.get("destination_id"):
            destination = Location.objects.filter(
                organization_id=organization_id,
                pk=values["destination_id"],
                is_active=True,
            ).first()
            if destination is None:
                return JsonResponse(
                    {"detail": "Active destination location not found."}, status=404
                )

        kind = values["kind"]
        decreases_source = (
            kind == StockMovement.Kind.ISSUE
            or (
                kind == StockMovement.Kind.ADJUSTMENT
                and values.get("direction") == StockMovement.Direction.DECREASE
            )
            or kind == StockMovement.Kind.TRANSFER
        )
        if decreases_source and _balance(product, location.pk) < values["quantity"]:
            return JsonResponse(
                {"detail": "Movement would make on-hand stock negative."}, status=409
            )

        try:
            with transaction.atomic():
                movement = StockMovement.objects.create(
                    organization_id=organization_id,
                    product=product,
                    kind=kind,
                    location=location,
                    destination=destination,
                    direction=values.get("direction", ""),
                    quantity=values["quantity"],
                    reason=values["reason"],
                    idempotency_key=values["idempotency_key"],
                    actor=request.user,
                )
        except IntegrityError:
            existing = StockMovement.objects.filter(
                organization_id=organization_id,
                idempotency_key=values["idempotency_key"],
            ).first()
            if existing and _same_request(existing, values):
                data = StockMovementSerializer(existing).data
                data["replayed"] = True
                return JsonResponse(data)
            return JsonResponse(
                {"detail": "Movement request conflicts with existing data."}, status=409
            )
    data = StockMovementSerializer(movement).data
    data["replayed"] = False
    return JsonResponse(data, status=201)


@require_http_methods(["POST"])
def job_material_issues_view(request, organization_id, job_id):
    _, error = _membership(request, organization_id, write=True)
    if error:
        return error
    values, error = _payload(request, JobMaterialIssueWriteSerializer)
    if error:
        return error
    canonical = {
        "reason": values["reason"],
        "lines": [
            {
                "product_id": line["product_id"],
                "location_id": line["location_id"],
                "quantity": format(line["quantity"], "f"),
            }
            for line in values["lines"]
        ],
    }
    signature = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        existing = (
            JobMaterialIssue.objects.filter(
                organization_id=organization_id,
                idempotency_key=values["idempotency_key"],
            )
            .prefetch_related("lines")
            .first()
        )
        if existing:
            if existing.job_id != job_id or existing.request_signature != signature:
                return JsonResponse(
                    {
                        "detail": "Idempotency key was already used for another job issue."
                    },
                    status=409,
                )
            data = JobMaterialIssueSerializer(existing).data
            data["replayed"] = True
            return JsonResponse(data)

        job = (
            Job.objects.select_for_update()
            .filter(organization_id=organization_id, pk=job_id)
            .first()
        )
        if job is None:
            return JsonResponse({"detail": "Job not found."}, status=404)
        product_ids = [line["product_id"] for line in values["lines"]]
        products = {
            product.pk: product
            for product in Product.objects.select_for_update().filter(
                organization_id=organization_id, pk__in=product_ids, is_active=True
            )
        }
        if len(products) != len(set(product_ids)):
            return JsonResponse(
                {"detail": "One or more active products were not found."}, status=404
            )
        location_ids = {line["location_id"] for line in values["lines"]}
        locations = {
            location.pk: location
            for location in Location.objects.filter(
                organization_id=organization_id, pk__in=location_ids, is_active=True
            )
        }
        if len(locations) != len(location_ids):
            return JsonResponse(
                {"detail": "One or more active locations were not found."}, status=404
            )

        # All stock-changing endpoints lock the organization before evaluating balances.
        for line in values["lines"]:
            product = products[line["product_id"]]
            if _balance(product, line["location_id"]) < line["quantity"]:
                return JsonResponse(
                    {"detail": f"Issue would make stock negative for {product.sku}."},
                    status=409,
                )

        issue = JobMaterialIssue.objects.create(
            organization_id=organization_id,
            job=job,
            actor=request.user,
            idempotency_key=values["idempotency_key"],
            request_signature=signature,
            reason=values["reason"],
        )
        for index, line in enumerate(values["lines"]):
            product = products[line["product_id"]]
            location = locations[line["location_id"]]
            issue_line = JobMaterialIssueLine.objects.create(
                issue=issue,
                product=product,
                location=location,
                product_sku=product.sku,
                product_name=product.name,
                base_unit=product.base_unit,
                location_code=location.code,
                quantity=line["quantity"],
            )
            StockMovement.objects.create(
                organization_id=organization_id,
                product=product,
                kind=StockMovement.Kind.ISSUE,
                location=location,
                quantity=line["quantity"],
                reason=f"Job #{job.pk}: {values['reason']}"[:500],
                idempotency_key=uuid.uuid5(values["idempotency_key"], str(index)),
                actor=request.user,
                source_job_material_issue_line=issue_line,
            )

    data = JobMaterialIssueSerializer(
        JobMaterialIssue.objects.prefetch_related("lines").get(pk=issue.pk)
    ).data
    data["replayed"] = False
    return JsonResponse(data, status=201)
