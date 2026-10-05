import json

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import ValidationError

from accounts.models import Membership
from .models import Customer, CustomerStatusHistory
from .serializers import CustomerSerializer

WRITERS = {
    Membership.Role.OWNER,
    Membership.Role.ADMIN,
    Membership.Role.SALES,
    Membership.Role.OPERATIONS,
}


@require_http_methods(["GET", "POST"])
def customers_view(request, organization_id):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    membership = Membership.objects.filter(
        user=request.user, organization_id=organization_id
    ).first()
    if membership is None:
        return JsonResponse({"detail": "Organization not found."}, status=404)
    if request.method == "GET":
        customers = Customer.objects.filter(organization_id=organization_id)
        status = request.GET.get("status", Customer.Status.ACTIVE)
        if status in {Customer.Status.ACTIVE, Customer.Status.ARCHIVED}:
            customers = customers.filter(status=status)
        elif status != "all":
            return JsonResponse(
                {"status": ["Choose active, archived, or all."]}, status=400
            )
        search = request.GET.get("search", "").strip()
        if search:
            customers = customers.filter(
                Q(name__icontains=search)
                | Q(contact_name__icontains=search)
                | Q(email__icontains=search)
                | Q(phone__icontains=search)
            )
        customers = customers.prefetch_related("status_history__actor")
        return JsonResponse({"results": CustomerSerializer(customers, many=True).data})
    if membership.role not in WRITERS:
        return JsonResponse(
            {"detail": "You do not have permission to add customers."}, status=403
        )
    try:
        data = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"detail": "A JSON object is required."}, status=400)
    serializer = CustomerSerializer(data=data)
    try:
        serializer.is_valid(raise_exception=True)
    except ValidationError as error:
        return JsonResponse(error.detail, status=400)
    if Customer.objects.filter(
        organization_id=organization_id, name=serializer.validated_data["name"]
    ).exists():
        return JsonResponse(
            {
                "name": [
                    "A customer with this name already exists in this organization."
                ]
            },
            status=400,
        )
    try:
        with transaction.atomic():
            customer = serializer.save(
                organization_id=organization_id, created_by=request.user
            )
    except IntegrityError:
        return JsonResponse(
            {
                "name": [
                    "A customer with this name already exists in this organization."
                ]
            },
            status=400,
        )
    return JsonResponse(CustomerSerializer(customer).data, status=201)


@require_http_methods(["PATCH", "POST"])
def customer_detail_view(request, organization_id, customer_id):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    membership = Membership.objects.filter(
        user=request.user, organization_id=organization_id
    ).first()
    if membership is None:
        return JsonResponse({"detail": "Organization not found."}, status=404)
    if membership.role not in WRITERS:
        return JsonResponse(
            {"detail": "You do not have permission to update customers."}, status=403
        )
    try:
        data = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"detail": "A JSON object is required."}, status=400)
    if request.method == "PATCH":
        customer = (
            Customer.objects.filter(organization_id=organization_id, id=customer_id)
            .prefetch_related("status_history__actor")
            .first()
        )
        if customer is None:
            return JsonResponse({"detail": "Customer not found."}, status=404)
        serializer = CustomerSerializer(customer, data=data, partial=True)
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as error:
            return JsonResponse(error.detail, status=400)
        if (
            Customer.objects.filter(
                organization_id=organization_id,
                name=serializer.validated_data.get("name", customer.name),
            )
            .exclude(pk=customer.pk)
            .exists()
        ):
            return JsonResponse(
                {
                    "name": [
                        "A customer with this name already exists in this organization."
                    ]
                },
                status=400,
            )
        try:
            with transaction.atomic():
                updated = serializer.save()
        except IntegrityError:
            return JsonResponse(
                {
                    "name": [
                        "A customer with this name already exists in this organization."
                    ]
                },
                status=400,
            )
        return JsonResponse(CustomerSerializer(updated).data)
    if data.get("action") not in {"archive", "restore"}:
        return JsonResponse({"action": ["Choose archive or restore."]}, status=400)
    next_status = (
        Customer.Status.ARCHIVED
        if data["action"] == "archive"
        else Customer.Status.ACTIVE
    )
    with transaction.atomic():
        customer = (
            Customer.objects.filter(organization_id=organization_id, id=customer_id)
            .select_for_update()
            .first()
        )
        if customer is None:
            return JsonResponse({"detail": "Customer not found."}, status=404)
        if customer.status != next_status:
            previous_status = customer.status
            customer.status = next_status
            customer.save(update_fields=["status", "updated_at"])
            CustomerStatusHistory.objects.create(
                customer=customer,
                previous_status=previous_status,
                status=next_status,
                actor=request.user,
            )
    return JsonResponse(CustomerSerializer(customer).data)
