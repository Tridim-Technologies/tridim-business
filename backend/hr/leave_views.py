import json

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import ValidationError

from accounts.models import Membership
from .leave_serializers import (
    LeaveRequestCreateSerializer,
    LeaveRequestSerializer,
    membership_can_manage_leave,
)
from .models import LeaveRequest, LeaveRequestHistory


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


def _queryset(organization_id, membership, user):
    requests = (
        LeaveRequest.objects.filter(
            membership__organization_id=organization_id,
            membership__user__is_active=True,
        )
        .select_related("membership__user", "reviewed_by")
        .prefetch_related("history__actor")
    )
    if not membership_can_manage_leave(membership):
        requests = requests.filter(membership=membership)
    return requests


@require_http_methods(["GET", "POST"])
def leave_requests_view(request, organization_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error

    if request.method == "GET":
        status = request.GET.get("status", "all")
        valid_statuses = {value for value, _label in LeaveRequest.Status.choices}
        if status != "all" and status not in valid_statuses:
            return JsonResponse(
                {"status": ["Choose a valid status or all."]}, status=400
            )
        requests = _queryset(organization_id, membership, request.user)
        if status != "all":
            requests = requests.filter(status=status)
        return JsonResponse(
            {
                "results": LeaveRequestSerializer(
                    requests, many=True, context={"request": request}
                ).data
            }
        )

    data, error = _json_object(request)
    if error:
        return error
    if set(data) - {"start_date", "end_date", "category", "note"}:
        return JsonResponse(
            {"detail": "Only dates, category, and a short note may be supplied."},
            status=400,
        )
    serializer = LeaveRequestCreateSerializer(data=data)
    try:
        serializer.is_valid(raise_exception=True)
    except ValidationError as exc:
        return JsonResponse(exc.detail, status=400)

    values = serializer.validated_data
    with transaction.atomic():
        locked_membership = Membership.objects.select_for_update().get(pk=membership.pk)
        overlap = LeaveRequest.objects.filter(
            membership=locked_membership,
            status__in=[LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED],
            start_date__lte=values["end_date"],
            end_date__gte=values["start_date"],
        ).exists()
        if overlap:
            return JsonResponse(
                {
                    "detail": "This request overlaps another pending or approved request."
                },
                status=409,
            )
        leave_request = LeaveRequest.objects.create(
            membership=locked_membership,
            start_date=values["start_date"],
            end_date=values["end_date"],
            category=values["category"],
            note=values["note"],
        )
        LeaveRequestHistory.objects.create(
            leave_request=leave_request,
            action=LeaveRequestHistory.Action.SUBMITTED,
            actor=request.user,
        )
    return JsonResponse(
        LeaveRequestSerializer(leave_request, context={"request": request}).data,
        status=201,
    )


@require_http_methods(["GET"])
def leave_request_detail_view(request, organization_id, leave_request_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error
    leave_request = (
        _queryset(organization_id, membership, request.user)
        .filter(pk=leave_request_id)
        .first()
    )
    if leave_request is None:
        return JsonResponse({"detail": "Leave request not found."}, status=404)
    return JsonResponse(
        LeaveRequestSerializer(leave_request, context={"request": request}).data
    )


@require_http_methods(["POST"])
def leave_request_transition_view(request, organization_id, leave_request_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error
    data, error = _json_object(request)
    if error:
        return error
    if set(data) - {"action", "reason"}:
        return JsonResponse(
            {"detail": "Only action and reason may be supplied."}, status=400
        )
    action = data.get("action")
    reason = data.get("reason", "")
    if action not in {"approve", "reject", "cancel"}:
        return JsonResponse(
            {"action": ["Choose approve, reject, or cancel."]}, status=400
        )
    if not isinstance(reason, str):
        return JsonResponse({"reason": ["Enter a short text reason."]}, status=400)
    reason = " ".join(reason.split())
    if len(reason) > 240:
        return JsonResponse(
            {"reason": ["Ensure this field has no more than 240 characters."]},
            status=400,
        )
    if action == "reject" and not reason:
        return JsonResponse(
            {"reason": ["A reason is required to reject a request."]}, status=400
        )

    with transaction.atomic():
        leave_request = (
            _queryset(organization_id, membership, request.user)
            .select_for_update()
            .filter(pk=leave_request_id)
            .first()
        )
        if leave_request is None:
            return JsonResponse({"detail": "Leave request not found."}, status=404)
        is_owner = leave_request.membership_id == membership.id
        is_manager = membership_can_manage_leave(membership)
        if action == "cancel":
            if not is_owner:
                return JsonResponse(
                    {"detail": "Only the requester can cancel this request."},
                    status=403,
                )
        elif not is_manager:
            return JsonResponse(
                {"detail": "You do not have permission to review leave requests."},
                status=403,
            )
        elif is_owner:
            return JsonResponse(
                {"detail": "You cannot review your own leave request."}, status=403
            )
        if leave_request.status != LeaveRequest.Status.PENDING:
            return JsonResponse(
                {"detail": "Only pending requests can be changed."}, status=409
            )

        if action == "approve":
            leave_request.status = LeaveRequest.Status.APPROVED
            history_action = LeaveRequestHistory.Action.APPROVED
        elif action == "reject":
            leave_request.status = LeaveRequest.Status.REJECTED
            history_action = LeaveRequestHistory.Action.REJECTED
        else:
            leave_request.status = LeaveRequest.Status.CANCELLED
            history_action = LeaveRequestHistory.Action.CANCELLED
        leave_request.decision_reason = reason
        if action != "cancel":
            leave_request.reviewed_by = request.user
            leave_request.reviewed_at = timezone.now()
        leave_request.save(
            update_fields=[
                "status",
                "decision_reason",
                "reviewed_by",
                "reviewed_at",
                "updated_at",
            ]
        )
        LeaveRequestHistory.objects.create(
            leave_request=leave_request,
            action=history_action,
            actor=request.user,
            reason=reason,
        )

    return JsonResponse(
        LeaveRequestSerializer(leave_request, context={"request": request}).data
    )
