import json

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import ValidationError

from accounts.models import Membership
from .models import Customer
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
