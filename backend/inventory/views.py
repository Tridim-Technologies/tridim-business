import hashlib
import json
import uuid
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import ValidationError

from accounts.models import Membership, Organization
from quotations.models import Job

from .models import (
    JobMaterialIssue,
    JobMaterialIssueLine,
    JobMaterialReservation,
    JobMaterialReservationLine,
    Location,
    Product,
    StockMovement,
)
from .serializers import (
    LocationSerializer,
    LocationWriteSerializer,
    JobMaterialIssueSerializer,
    JobMaterialIssueWriteSerializer,
    JobMaterialReservationWriteSerializer,
    MovementWriteSerializer,
    ProductSerializer,
    ProductWriteSerializer,
    StockMovementSerializer,
)
from .services import (
    available_stock_balances,
    location_reserved_balances,
    location_stock_balances,
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
STOREFRONT_MANAGERS = {Membership.Role.OWNER, Membership.Role.ADMIN}
STOREFRONT_FIELDS = {
    "storefront_description",
    "storefront_price",
    "is_published",
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
    reserved = location_reserved_balances(organization_id)
    product_data = ProductSerializer(products, many=True).data
    location_data = LocationSerializer(locations, many=True).data
    for product in product_data:
        product["balances"] = []
        for location in location_data:
            key = (product["id"], location["id"])
            quantity = totals.get(key, Decimal("0.000"))
            reserved_quantity = reserved.get(key, Decimal("0.000"))
            product["balances"].append(
                {
                    "location_id": location["id"],
                    "location_code": location["code"],
                    "quantity": format(quantity, ".3f"),
                    "reserved_quantity": format(reserved_quantity, ".3f"),
                    "available_quantity": format(quantity - reserved_quantity, ".3f"),
                }
            )
        product["on_hand_quantity"] = format(
            sum(
                (Decimal(balance["quantity"]) for balance in product["balances"]),
                Decimal("0.000"),
            ),
            ".3f",
        )
        product["reserved_quantity"] = format(
            sum(
                (
                    Decimal(balance["reserved_quantity"])
                    for balance in product["balances"]
                ),
                Decimal("0.000"),
            ),
            ".3f",
        )
        product["available_quantity"] = format(
            sum(
                (
                    Decimal(balance["available_quantity"])
                    for balance in product["balances"]
                ),
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
    membership, error = _membership(request, organization_id, write=True)
    if error:
        return error
    values, error = _payload(request, ProductWriteSerializer)
    if error:
        return error
    if STOREFRONT_FIELDS.intersection(values) and membership.role not in STOREFRONT_MANAGERS:
        return JsonResponse(
            {"detail": "Only organization owners and admins can manage public listings."},
            status=403,
        )
    if values.get("is_published") and (
        not values.get("storefront_description", "").strip()
        or values.get("storefront_price") is None
    ):
        return JsonResponse(
            {
                "detail": "Add a public description and price before publishing a product."
            },
            status=400,
        )
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
    membership, error = _membership(request, organization_id, write=True)
    if error:
        return error
    values, error = _payload(request, ProductWriteSerializer, partial=True)
    if error:
        return error
    if not values:
        return JsonResponse({"detail": "Provide product fields to update."}, status=400)
    if STOREFRONT_FIELDS.intersection(values) and membership.role not in STOREFRONT_MANAGERS:
        return JsonResponse(
            {"detail": "Only organization owners and admins can manage public listings."},
            status=403,
        )
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        product = (
            Product.objects.select_for_update()
            .filter(organization_id=organization_id, pk=product_id)
            .first()
        )
        if product is None:
            return JsonResponse({"detail": "Product not found."}, status=404)
        final_description = values.get(
            "storefront_description", product.storefront_description
        )
        final_price = values.get("storefront_price", product.storefront_price)
        final_published = values.get("is_published", product.is_published)
        if final_published and (not final_description.strip() or final_price is None):
            return JsonResponse(
                {
                    "detail": "Add a public description and price before publishing a product."
                },
                status=400,
            )
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
        if values.get("is_active") is False and product.is_active:
            outstanding = location_reserved_balances(organization_id)
            if any(
                reserved > 0
                for (reserved_product_id, _location_id), reserved in outstanding.items()
                if reserved_product_id == product.pk
            ):
                return JsonResponse(
                    {
                        "detail": "Release outstanding job reservations before deactivating this product."
                    },
                    status=409,
                )
            values["is_published"] = False
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
        if decreases_source:
            on_hand = _balance(product, location.pk)
            available = available_stock_balances(organization_id).get(
                (product.pk, location.pk), Decimal("0.000")
            )
            if on_hand < values["quantity"]:
                return JsonResponse(
                    {"detail": "Movement would make on-hand stock negative."},
                    status=409,
                )
            if available < values["quantity"]:
                return JsonResponse(
                    {"detail": "Movement would consume stock reserved for a job."},
                    status=409,
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
                **(
                    {"reservation_line_id": line["reservation_line_id"]}
                    if line.get("reservation_line_id") is not None
                    else {}
                ),
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

        reservation_line_ids = {
            line["reservation_line_id"]
            for line in values["lines"]
            if line.get("reservation_line_id") is not None
        }
        reservation_lines = {
            reservation_line.pk: reservation_line
            for reservation_line in JobMaterialReservationLine.objects.select_for_update()
            .filter(
                pk__in=reservation_line_ids,
                reservation__organization_id=organization_id,
                reservation__status=JobMaterialReservation.Status.ACTIVE,
                reservation__job_id=job_id,
            )
            .select_related("reservation")
        }
        if len(reservation_lines) != len(reservation_line_ids):
            return JsonResponse(
                {"detail": "One or more active job reservations were not found."},
                status=404,
            )
        consumed = {
            row["reservation_line_id"]: row["total"]
            for row in JobMaterialIssueLine.objects.filter(
                reservation_line_id__in=reservation_line_ids
            )
            .values("reservation_line_id")
            .annotate(total=Sum("quantity"))
        }
        available_balances = available_stock_balances(organization_id)

        # All stock-changing endpoints lock the organization before evaluating balances.
        for line in values["lines"]:
            product = products[line["product_id"]]
            if _balance(product, line["location_id"]) < line["quantity"]:
                return JsonResponse(
                    {"detail": f"Issue would make stock negative for {product.sku}."},
                    status=409,
                )
            reservation_line_id = line.get("reservation_line_id")
            if reservation_line_id is None:
                if (
                    available_balances.get(
                        (product.pk, line["location_id"]), Decimal("0.000")
                    )
                    < line["quantity"]
                ):
                    return JsonResponse(
                        {
                            "detail": f"Issue would consume stock reserved for a job for {product.sku}."
                        },
                        status=409,
                    )
                continue

            reservation_line = reservation_lines[reservation_line_id]
            if (
                reservation_line.product_id != product.pk
                or reservation_line.location_id != line["location_id"]
            ):
                return JsonResponse(
                    {"detail": "Reserved product and location must match the issue."},
                    status=400,
                )
            remaining = reservation_line.quantity - consumed.get(
                reservation_line_id, Decimal("0.000")
            )
            if remaining < line["quantity"]:
                return JsonResponse(
                    {"detail": "Issue exceeds the remaining reserved quantity."},
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
                reservation_line_id=line.get("reservation_line_id"),
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


def _reservation_data(reservation):
    lines = list(
        JobMaterialReservationLine.objects.filter(reservation=reservation).order_by(
            "id"
        )
    )
    issued = {
        row["reservation_line_id"]: row["total"]
        for row in JobMaterialIssueLine.objects.filter(
            reservation_line_id__in=[line.pk for line in lines]
        )
        .values("reservation_line_id")
        .annotate(total=Sum("quantity"))
    }
    return {
        "id": reservation.pk,
        "job_id": reservation.job_id,
        "status": reservation.status,
        "reason": reservation.reason,
        "actor": reservation.actor.get_username(),
        "idempotency_key": str(reservation.idempotency_key),
        "created_at": reservation.created_at,
        "released_by": (
            reservation.released_by.get_username() if reservation.released_by else None
        ),
        "released_at": reservation.released_at,
        "lines": [
            {
                "id": line.pk,
                "product_id": line.product_id,
                "location_id": line.location_id,
                "product_sku": line.product_sku,
                "product_name": line.product_name,
                "base_unit": line.base_unit,
                "location_code": line.location_code,
                "quantity": format(line.quantity, ".3f"),
                "issued_quantity": format(issued.get(line.pk, Decimal("0.000")), ".3f"),
                "unissued_quantity": format(
                    line.quantity - issued.get(line.pk, Decimal("0.000")), ".3f"
                ),
                "remaining_quantity": format(
                    (
                        line.quantity - issued.get(line.pk, Decimal("0.000"))
                        if reservation.status == JobMaterialReservation.Status.ACTIVE
                        else Decimal("0.000")
                    ),
                    ".3f",
                ),
            }
            for line in lines
        ],
    }


@require_http_methods(["GET", "POST"])
def job_material_reservations_view(request, organization_id, job_id):
    membership, error = _membership(
        request, organization_id, write=request.method == "POST"
    )
    if error:
        return error
    if request.method == "GET":
        if not Job.objects.filter(organization_id=organization_id, pk=job_id).exists():
            return JsonResponse({"detail": "Job not found."}, status=404)
        reservations = (
            JobMaterialReservation.objects.filter(
                organization_id=organization_id, job_id=job_id
            )
            .select_related("actor", "released_by")
            .prefetch_related("lines")
        )
        return JsonResponse(
            {"results": [_reservation_data(item) for item in reservations]}
        )

    values, error = _payload(request, JobMaterialReservationWriteSerializer)
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
        # Stock reservation writes serialize with all stock movements on this tenant.
        Organization.objects.select_for_update().get(pk=organization_id)
        existing = JobMaterialReservation.objects.filter(
            organization_id=organization_id,
            idempotency_key=values["idempotency_key"],
        ).first()
        if existing:
            if existing.job_id != job_id or existing.request_signature != signature:
                return JsonResponse(
                    {"detail": "Reservation key was used for different data."},
                    status=409,
                )
            data = _reservation_data(existing)
            data["replayed"] = True
            return JsonResponse(data)

        job = (
            Job.objects.select_for_update()
            .filter(organization_id=organization_id, pk=job_id)
            .first()
        )
        if job is None:
            return JsonResponse({"detail": "Job not found."}, status=404)
        product_ids = {line["product_id"] for line in values["lines"]}
        products = {
            product.pk: product
            for product in Product.objects.select_for_update().filter(
                organization_id=organization_id, pk__in=product_ids, is_active=True
            )
        }
        if len(products) != len(product_ids):
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

        available = available_stock_balances(organization_id)
        for line in values["lines"]:
            key = (line["product_id"], line["location_id"])
            if available.get(key, Decimal("0.000")) < line["quantity"]:
                product = products[line["product_id"]]
                return JsonResponse(
                    {
                        "detail": f"Insufficient unreserved stock for {product.sku} at the selected location."
                    },
                    status=409,
                )

        reservation = JobMaterialReservation.objects.create(
            organization_id=organization_id,
            job=job,
            actor=request.user,
            idempotency_key=values["idempotency_key"],
            request_signature=signature,
            reason=values["reason"],
        )
        for line in values["lines"]:
            product = products[line["product_id"]]
            location = locations[line["location_id"]]
            JobMaterialReservationLine.objects.create(
                reservation=reservation,
                product=product,
                location=location,
                product_sku=product.sku,
                product_name=product.name,
                base_unit=product.base_unit,
                location_code=location.code,
                quantity=line["quantity"],
            )

    data = _reservation_data(
        JobMaterialReservation.objects.select_related("actor", "released_by").get(
            pk=reservation.pk
        )
    )
    data["replayed"] = False
    return JsonResponse(data, status=201)


@require_http_methods(["POST"])
def job_material_reservation_release_view(
    request, organization_id, job_id, reservation_id
):
    _, error = _membership(request, organization_id, write=True)
    if error:
        return error
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        reservation = (
            JobMaterialReservation.objects.select_for_update()
            .filter(
                organization_id=organization_id,
                job_id=job_id,
                pk=reservation_id,
            )
            .select_related("actor", "released_by")
            .first()
        )
        if reservation is None:
            return JsonResponse({"detail": "Reservation not found."}, status=404)
        if reservation.status == JobMaterialReservation.Status.RELEASED:
            data = _reservation_data(reservation)
            data["replayed"] = True
            return JsonResponse(data)
        reservation.status = JobMaterialReservation.Status.RELEASED
        reservation.released_by = request.user
        reservation.released_at = timezone.now()
        reservation.save(update_fields=["status", "released_by", "released_at"])
    data = _reservation_data(reservation)
    data["replayed"] = False
    return JsonResponse(data)
