import json

from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import ValidationError

from accounts.models import Membership

from .expense_serializers import (
    ExpenseClaimFinanceSerializer,
    ExpenseClaimSerializer,
    ExpenseClaimTransitionSerializer,
    ExpenseClaimWriteSerializer,
)
from .job_views import JOB_MANAGERS, _membership
from .models import (
    ExpenseClaim,
    ExpenseClaimEvidence,
    ExpenseClaimHistory,
    Job,
    JobAssignment,
)


def _payload(request):
    try:
        data = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse({"detail": "Invalid JSON."}, status=400)
    if not isinstance(data, dict):
        return None, JsonResponse({"detail": "Expected a JSON object."}, status=400)
    return data, None


def _validated(serializer):
    try:
        serializer.is_valid(raise_exception=True)
    except ValidationError as error:
        return None, JsonResponse(error.detail, status=400)
    return serializer.validated_data, None


def _claim_query(organization_id, membership, user):
    claims = ExpenseClaim.objects.filter(
        organization_id=organization_id, job__organization_id=organization_id
    ).select_related("claimant")
    if membership.role == Membership.Role.FINANCE:
        claims = claims.filter(
            Q(claimant=user) | Q(status=ExpenseClaim.Status.APPROVED)
        )
    elif membership.role not in JOB_MANAGERS:
        claims = claims.filter(claimant=user)
    return claims.prefetch_related("history__actor", "evidence")


def _serialize(claim, membership, user):
    if membership.role == Membership.Role.FINANCE and claim.claimant_id != user.pk:
        return ExpenseClaimFinanceSerializer(claim).data
    return ExpenseClaimSerializer(claim).data


def _history(claim, action, previous_status, actor, reason=""):
    ExpenseClaimHistory.objects.create(
        claim=claim,
        action=action,
        previous_status=previous_status,
        status=claim.status,
        actor=actor,
        version=claim.version,
        revision=claim.revision,
        expense_date=claim.expense_date,
        amount=claim.amount,
        currency=claim.currency,
        category=claim.category,
        merchant=claim.merchant,
        purpose=claim.purpose,
        missing_receipt_explanation=claim.missing_receipt_explanation,
        reason=reason,
    )


def _assigned(job, user):
    return JobAssignment.objects.filter(
        job=job, user=user, unassigned_at__isnull=True
    ).exists()


def _current_membership(organization_id, user):
    return (
        Membership.objects.select_for_update()
        .filter(organization_id=organization_id, user=user)
        .first()
    )


@require_http_methods(["GET", "POST"])
def expense_claims_view(request, organization_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error
    if request.method == "GET":
        claims = _claim_query(organization_id, membership, request.user)
        return JsonResponse(
            {
                "results": [
                    _serialize(claim, membership, request.user) for claim in claims
                ]
            }
        )

    payload, error = _payload(request)
    if error:
        return error
    values, error = _validated(ExpenseClaimWriteSerializer(data=payload))
    if error:
        return error
    if "job_id" not in values:
        return JsonResponse({"job_id": ["This field is required."]}, status=400)
    if "revision" in values:
        return JsonResponse(
            {"revision": ["Do not set a new claim revision."]}, status=400
        )
    with transaction.atomic():
        if _current_membership(organization_id, request.user) is None:
            return JsonResponse({"detail": "Organization not found."}, status=404)
        job = (
            Job.objects.select_for_update()
            .filter(organization_id=organization_id, pk=values["job_id"])
            .first()
        )
        if job is None:
            return JsonResponse({"detail": "Job not found."}, status=404)
        if not _assigned(job, request.user):
            return JsonResponse({"detail": "Job not found."}, status=404)
        if job.status == Job.Status.CANCELLED:
            return JsonResponse(
                {"detail": "Claims cannot be created for a cancelled job."}, status=409
            )
        claim = ExpenseClaim.objects.create(
            organization_id=organization_id,
            job=job,
            claimant=request.user,
            expense_date=values["expense_date"],
            amount=values["amount"],
            currency=values["currency"],
            category=values["category"],
            merchant=values.get("merchant", ""),
            purpose=values["purpose"],
            missing_receipt_explanation=values.get("missing_receipt_explanation", ""),
        )
        _history(claim, "create", "", request.user)
    return JsonResponse(_serialize(claim, membership, request.user), status=201)


@require_http_methods(["GET", "PATCH"])
def expense_claim_detail_view(request, organization_id, claim_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error
    if request.method == "GET":
        claim = (
            _claim_query(organization_id, membership, request.user)
            .filter(pk=claim_id)
            .first()
        )
        if claim is None:
            return JsonResponse({"detail": "Claim not found."}, status=404)
        return JsonResponse(_serialize(claim, membership, request.user))

    payload, error = _payload(request)
    if error:
        return error
    values, error = _validated(ExpenseClaimWriteSerializer(data=payload, partial=True))
    if error:
        return error
    if "revision" not in values:
        return JsonResponse({"revision": ["This field is required."]}, status=400)
    if "job_id" in values:
        return JsonResponse(
            {"job_id": ["A claim cannot move to another job."]}, status=400
        )
    changes = {key: value for key, value in values.items() if key != "revision"}
    if not changes:
        return JsonResponse({"detail": "Provide claim fields to update."}, status=400)
    with transaction.atomic():
        if _current_membership(organization_id, request.user) is None:
            return JsonResponse({"detail": "Organization not found."}, status=404)
        claim = (
            ExpenseClaim.objects.select_for_update()
            .filter(
                pk=claim_id,
                organization_id=organization_id,
                job__organization_id=organization_id,
                claimant=request.user,
            )
            .first()
        )
        if claim is None:
            return JsonResponse({"detail": "Claim not found."}, status=404)
        if claim.revision != values["revision"]:
            return JsonResponse(
                {"detail": "Claim changed; refresh and retry."}, status=409
            )
        if claim.status not in {
            ExpenseClaim.Status.DRAFT,
            ExpenseClaim.Status.RETURNED,
        }:
            return JsonResponse(
                {"detail": "Only draft or returned claims can be edited."}, status=409
            )
        for key, value in changes.items():
            setattr(claim, key, value)
        claim.revision += 1
        claim.save(update_fields=[*changes, "revision", "updated_at"])
        _history(claim, "edit", claim.status, request.user)
    return JsonResponse(
        ExpenseClaimSerializer(
            _claim_query(organization_id, membership, request.user).get(pk=claim_id)
        ).data
    )


@require_http_methods(["POST"])
def expense_claim_transition_view(request, organization_id, claim_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error
    payload, error = _payload(request)
    if error:
        return error
    values, error = _validated(ExpenseClaimTransitionSerializer(data=payload))
    if error:
        return error
    action = values["action"]
    with transaction.atomic():
        current_membership = _current_membership(organization_id, request.user)
        if current_membership is None:
            return JsonResponse({"detail": "Organization not found."}, status=404)
        claim = (
            ExpenseClaim.objects.select_for_update()
            .filter(
                pk=claim_id,
                organization_id=organization_id,
                job__organization_id=organization_id,
            )
            .first()
        )
        if claim is None:
            return JsonResponse({"detail": "Claim not found."}, status=404)
        own = claim.claimant_id == request.user.pk
        reviewer = current_membership.role in JOB_MANAGERS and not own
        if (action in {"submit", "resubmit", "withdraw"} and not own) or (
            action in {"return", "waive", "approve", "reject"} and not reviewer
        ):
            return JsonResponse({"detail": "Claim not found."}, status=404)
        if claim.revision != values["revision"]:
            return JsonResponse(
                {"detail": "Claim changed; refresh and retry."}, status=409
            )
        previous = claim.status
        reason = values.get("reason", "")
        if action == "submit":
            if claim.status != ExpenseClaim.Status.DRAFT:
                return JsonResponse(
                    {"detail": "Only drafts can be submitted."}, status=409
                )
            job = Job.objects.select_for_update().get(pk=claim.job_id)
            if job.status == Job.Status.CANCELLED or not _assigned(job, request.user):
                return JsonResponse(
                    {"detail": "A current job assignment is required."}, status=409
                )
            if (
                not claim.missing_receipt_explanation
                and not claim.evidence.filter(
                    state=ExpenseClaimEvidence.State.ACCEPTED,
                    claim_version=claim.version,
                ).exists()
            ):
                return JsonResponse(
                    {
                        "missing_receipt_explanation": [
                            "Explain why the receipt is missing."
                        ]
                    },
                    status=400,
                )
            claim.status = ExpenseClaim.Status.SUBMITTED
        elif action == "resubmit":
            if claim.status != ExpenseClaim.Status.RETURNED:
                return JsonResponse(
                    {"detail": "Only returned claims can be resubmitted."}, status=409
                )
            last_event = claim.history.last()
            has_next_version_evidence = claim.evidence.filter(
                state=ExpenseClaimEvidence.State.ACCEPTED,
                claim_version=claim.version + 1,
            ).exists()
            if (
                last_event is None or last_event.action != "edit"
            ) and not has_next_version_evidence:
                return JsonResponse(
                    {"detail": "Correct the returned claim before resubmitting."},
                    status=409,
                )
            if (
                not claim.missing_receipt_explanation
                and not claim.evidence.filter(
                    state=ExpenseClaimEvidence.State.ACCEPTED,
                    claim_version=claim.version + 1,
                ).exists()
            ):
                return JsonResponse(
                    {
                        "missing_receipt_explanation": [
                            "Explain why the receipt is missing."
                        ]
                    },
                    status=400,
                )
            claim.version += 1
            claim.waived_version = None
            claim.status = ExpenseClaim.Status.SUBMITTED
        elif action == "withdraw":
            if claim.status not in {
                ExpenseClaim.Status.DRAFT,
                ExpenseClaim.Status.SUBMITTED,
                ExpenseClaim.Status.RETURNED,
            }:
                return JsonResponse(
                    {"detail": "Only pending claims can be withdrawn."}, status=409
                )
            claim.status = ExpenseClaim.Status.WITHDRAWN
        else:
            if claim.status != ExpenseClaim.Status.SUBMITTED:
                return JsonResponse(
                    {"detail": "Only submitted claims can be reviewed."}, status=409
                )
            if action == "return":
                claim.status = ExpenseClaim.Status.RETURNED
                claim.waived_version = None
            elif action == "waive":
                if claim.waived_version == claim.version:
                    return JsonResponse(
                        {"detail": "This version is already waived."}, status=409
                    )
                if claim.evidence.filter(
                    state=ExpenseClaimEvidence.State.ACCEPTED,
                    claim_version=claim.version,
                ).exists():
                    return JsonResponse(
                        {
                            "detail": "A receipt is attached; a waiver is not applicable."
                        },
                        status=409,
                    )
                if not claim.missing_receipt_explanation:
                    return JsonResponse(
                        {"detail": "The claimant must explain the missing receipt."},
                        status=409,
                    )
                claim.waived_version = claim.version
            elif action == "approve":
                has_evidence = claim.evidence.filter(
                    state=ExpenseClaimEvidence.State.ACCEPTED,
                    claim_version=claim.version,
                ).exists()
                if claim.waived_version != claim.version and not has_evidence:
                    return JsonResponse(
                        {
                            "detail": "Current-version receipt evidence or a reasoned waiver is required."
                        },
                        status=409,
                    )
                claim.status = ExpenseClaim.Status.APPROVED
                claim.approved_at = timezone.now()
            else:
                claim.status = ExpenseClaim.Status.REJECTED
        claim.revision += 1
        claim.save(
            update_fields=[
                "status",
                "version",
                "revision",
                "waived_version",
                "approved_at",
                "updated_at",
            ]
        )
        _history(claim, action, previous, request.user, reason=reason)
    return JsonResponse(
        _serialize(
            _claim_query(organization_id, membership, request.user).get(pk=claim_id),
            membership,
            request.user,
        )
    )
