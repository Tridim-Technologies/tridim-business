import json

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import ValidationError

from accounts.models import Membership
from .models import EmployeeProfile
from .serializers import EmployeeProfileSerializer

HR_READERS = {
    Membership.Role.OWNER,
    Membership.Role.ADMIN,
    Membership.Role.OPERATIONS,
    Membership.Role.EMPLOYEE,
}
HR_MANAGERS = {
    Membership.Role.OWNER,
    Membership.Role.ADMIN,
    Membership.Role.OPERATIONS,
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


def _json_object(request):
    try:
        data = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse({"detail": "Invalid JSON."}, status=400)
    if not isinstance(data, dict):
        return None, JsonResponse({"detail": "A JSON object is required."}, status=400)
    return data, None


@require_http_methods(["GET", "POST"])
def employees_view(request, organization_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error
    if membership.role not in HR_READERS:
        return JsonResponse(
            {"detail": "You do not have permission to view employees."}, status=403
        )

    if request.method == "GET":
        status = request.GET.get("status", "active")
        if status not in {"active", "all"}:
            return JsonResponse({"status": ["Choose active or all."]}, status=400)
        if status == "all" and membership.role not in HR_MANAGERS:
            return JsonResponse(
                {"detail": "Only HR managers can view inactive profiles."}, status=403
            )
        profiles = EmployeeProfile.objects.filter(
            membership__organization_id=organization_id,
            membership__user__is_active=True,
        ).select_related("membership__user")
        if status == "active":
            profiles = profiles.filter(is_active=True)
        data = {
            "results": EmployeeProfileSerializer(
                profiles,
                many=True,
                context={"include_account_username": membership.role in HR_MANAGERS},
            ).data
        }
        if membership.role in HR_MANAGERS:
            profiled = EmployeeProfile.objects.filter(
                membership__organization_id=organization_id
            ).values_list("membership_id", flat=True)
            available = (
                Membership.objects.filter(
                    organization_id=organization_id, user__is_active=True
                )
                .exclude(id__in=profiled)
                .select_related("user")
                .order_by("user__username")
            )
            data["members"] = [
                {"id": item.id, "username": item.user.get_username()}
                for item in available
            ]
        return JsonResponse(data)

    if membership.role not in HR_MANAGERS:
        return JsonResponse(
            {"detail": "You do not have permission to manage employees."}, status=403
        )
    data, error = _json_object(request)
    if error:
        return error
    serializer = EmployeeProfileSerializer(
        data=data, context={"organization_id": organization_id}
    )
    try:
        serializer.is_valid(raise_exception=True)
    except ValidationError as exc:
        return JsonResponse(exc.detail, status=400)
    try:
        with transaction.atomic():
            profile = serializer.save(created_by=request.user)
    except IntegrityError:
        return JsonResponse(
            {"membership_id": ["This member already has an employee profile."]},
            status=400,
        )
    return JsonResponse(
        EmployeeProfileSerializer(
            profile, context={"include_account_username": True}
        ).data,
        status=201,
    )


@require_http_methods(["PATCH"])
def employee_detail_view(request, organization_id, profile_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error
    if membership.role not in HR_MANAGERS:
        return JsonResponse(
            {"detail": "You do not have permission to manage employees."}, status=403
        )
    profile = (
        EmployeeProfile.objects.filter(
            id=profile_id,
            membership__organization_id=organization_id,
            membership__user__is_active=True,
        )
        .select_related("membership__user")
        .first()
    )
    if profile is None:
        return JsonResponse({"detail": "Employee not found."}, status=404)
    data, error = _json_object(request)
    if error:
        return error
    serializer = EmployeeProfileSerializer(
        profile,
        data=data,
        partial=True,
        context={"organization_id": organization_id},
    )
    try:
        serializer.is_valid(raise_exception=True)
    except ValidationError as exc:
        return JsonResponse(exc.detail, status=400)
    updated = serializer.save()
    return JsonResponse(
        EmployeeProfileSerializer(
            updated, context={"include_account_username": True}
        ).data
    )
