import json

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import ValidationError

from accounts.models import Membership
from customers.models import Customer

from .models import Job, Quotation, QuotationLine, QuotationStatusHistory
from .serializers import QuotationCreateSerializer, QuotationSerializer

QUOTE_WRITERS = {Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.SALES}
ACCEPTORS = {Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.OPERATIONS}
TRANSITIONS = {
    Quotation.Status.DRAFT: {"send": Quotation.Status.SENT},
    Quotation.Status.SENT: {
        "accept": Quotation.Status.ACCEPTED,
        "reject": Quotation.Status.REJECTED,
        "withdraw": Quotation.Status.WITHDRAWN,
    },
}


def _membership(request, organization_id):
    if not request.user.is_authenticated:
        return None, JsonResponse({"detail": "Authentication required."}, status=401)
    membership = Membership.objects.filter(
        user=request.user, organization_id=organization_id
    ).first()
    if membership is None:
        return None, JsonResponse({"detail": "Organization not found."}, status=404)
    return membership, None


def _quotation(organization_id, quotation_id):
    return (
        Quotation.objects.filter(organization_id=organization_id, id=quotation_id)
        .select_related("customer")
        .prefetch_related("lines", "status_history__actor")
        .first()
    )


@require_http_methods(["GET", "POST"])
def quotations_view(request, organization_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error
    if request.method == "GET":
        quotes = (
            Quotation.objects.filter(organization_id=organization_id)
            .select_related("customer")
            .prefetch_related("lines", "status_history__actor")
        )
        return JsonResponse({"results": QuotationSerializer(quotes, many=True).data})
    if membership.role not in QUOTE_WRITERS:
        return JsonResponse(
            {"detail": "You do not have permission to create quotations."}, status=403
        )
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"detail": "A JSON object is required."}, status=400)
    serializer = QuotationCreateSerializer(data=payload)
    try:
        serializer.is_valid(raise_exception=True)
    except ValidationError as validation_error:
        return JsonResponse(validation_error.detail, status=400)
    values = serializer.validated_data
    customer = Customer.objects.filter(
        id=values["customer_id"], organization_id=organization_id
    ).first()
    if customer is None:
        return JsonResponse(
            {"customer_id": ["Select a customer in this organization."]}, status=400
        )
    if values["valid_until"] < timezone.localdate():
        return JsonResponse(
            {"valid_until": ["The expiry date must be today or later."]}, status=400
        )
    try:
        with transaction.atomic():
            quotation = Quotation.objects.create(
                organization_id=organization_id,
                customer=customer,
                currency=values["currency"].upper(),
                valid_until=values["valid_until"],
                created_by=request.user,
            )
            QuotationLine.objects.bulk_create(
                [
                    QuotationLine(quotation=quotation, position=index, **line)
                    for index, line in enumerate(values["lines"])
                ]
            )
            QuotationStatusHistory.objects.create(
                quotation=quotation,
                previous_status="",
                status=Quotation.Status.DRAFT,
                actor=request.user,
                note="Quotation created",
            )
    except IntegrityError:
        return JsonResponse(
            {"detail": "The quotation could not be created."}, status=400
        )
    return JsonResponse(QuotationSerializer(quotation).data, status=201)


@require_http_methods(["GET"])
def quotation_detail_view(request, organization_id, quotation_id):
    _, error = _membership(request, organization_id)
    if error:
        return error
    quotation = _quotation(organization_id, quotation_id)
    if quotation is None:
        return JsonResponse({"detail": "Quotation not found."}, status=404)
    return JsonResponse(QuotationSerializer(quotation).data)


@require_http_methods(["POST"])
def quotation_transition_view(request, organization_id, quotation_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    if not isinstance(payload, dict) or payload.get("action") not in {
        "send",
        "accept",
        "reject",
        "withdraw",
    }:
        return JsonResponse(
            {"action": ["Choose send, accept, reject, or withdraw."]}, status=400
        )
    action = payload["action"]
    if action == "accept" and membership.role not in ACCEPTORS:
        return JsonResponse(
            {"detail": "You do not have permission to accept work."}, status=403
        )
    if action != "accept" and membership.role not in QUOTE_WRITERS:
        return JsonResponse(
            {"detail": "You do not have permission to update quotations."}, status=403
        )
    with transaction.atomic():
        quotation = (
            Quotation.objects.filter(organization_id=organization_id, id=quotation_id)
            .select_for_update()
            .first()
        )
        if quotation is None:
            return JsonResponse({"detail": "Quotation not found."}, status=404)
        if (
            quotation.status in {Quotation.Status.DRAFT, Quotation.Status.SENT}
            and quotation.valid_until < timezone.localdate()
        ):
            previous = quotation.status
            quotation.status = Quotation.Status.EXPIRED
            quotation.save(update_fields=["status", "updated_at"])
            QuotationStatusHistory.objects.create(
                quotation=quotation,
                previous_status=previous,
                status=Quotation.Status.EXPIRED,
                actor=request.user,
                note="Quotation validity date passed",
            )
            return JsonResponse({"detail": "This quotation has expired."}, status=409)
        if action == "accept" and quotation.status == Quotation.Status.ACCEPTED:
            job = Job.objects.filter(source_quotation=quotation).first()
            if job:
                return JsonResponse(
                    QuotationSerializer(_quotation(organization_id, quotation_id)).data
                )
        if action not in TRANSITIONS.get(quotation.status, {}):
            return JsonResponse(
                {"detail": f"Cannot {action} a {quotation.status} quotation."},
                status=409,
            )
        previous = quotation.status
        next_status = TRANSITIONS[previous][action]
        quotation.status = next_status
        quotation.save(update_fields=["status", "updated_at"])
        QuotationStatusHistory.objects.create(
            quotation=quotation,
            previous_status=previous,
            status=next_status,
            actor=request.user,
            note=(
                payload.get("note", "")[:240]
                if isinstance(payload.get("note", ""), str)
                else ""
            ),
        )
        if action == "accept":
            Job.objects.get_or_create(
                source_quotation=quotation,
                defaults={
                    "organization_id": organization_id,
                    "customer_id": quotation.customer_id,
                    "created_by": request.user,
                },
            )
    return JsonResponse(
        QuotationSerializer(_quotation(organization_id, quotation_id)).data
    )
