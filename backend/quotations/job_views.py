import json

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import ValidationError

from accounts.models import Membership

from .job_serializers import (
    JobAssignmentCreateSerializer,
    JobNoteCreateSerializer,
    JobSerializer,
    JobTimeEntryReviewSerializer,
    JobTimeEntrySerializer,
    JobTimeEntryWriteSerializer,
    JobUpdateSerializer,
)
from .models import (
    Job,
    JobAssignment,
    JobDueDateHistory,
    JobNote,
    JobStatusHistory,
    JobTimeEntry,
    JobTimeEntryHistory,
)

JOB_MANAGERS = {
    Membership.Role.OWNER,
    Membership.Role.ADMIN,
    Membership.Role.OPERATIONS,
}
JOB_TRANSITIONS = {
    Job.Status.OPEN: {
        Job.Status.IN_PROGRESS,
        Job.Status.BLOCKED,
        Job.Status.CANCELLED,
    },
    Job.Status.IN_PROGRESS: {
        Job.Status.BLOCKED,
        Job.Status.COMPLETED,
        Job.Status.CANCELLED,
    },
    Job.Status.BLOCKED: {Job.Status.IN_PROGRESS, Job.Status.CANCELLED},
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


def _record_time_entry_history(entry, previous_status, actor, reason=""):
    JobTimeEntryHistory.objects.create(
        entry=entry,
        previous_status=previous_status,
        status=entry.status,
        actor=actor,
        work_date=entry.work_date,
        hours=entry.hours,
        description=entry.description,
        reason=reason,
    )


def _time_entry_query(job, membership, user):
    entries = JobTimeEntry.objects.filter(job=job).select_related("employee")
    if membership.role == Membership.Role.EMPLOYEE:
        entries = entries.filter(employee=user)
    return entries.prefetch_related("history__actor")


def _jobs_for_member(organization_id, membership, user):
    jobs = Job.objects.filter(organization_id=organization_id)
    if membership.role == Membership.Role.EMPLOYEE:
        jobs = jobs.filter(
            assignments__user=user, assignments__unassigned_at__isnull=True
        ).distinct()
    assignments = JobAssignment.objects.select_related(
        "user", "assigned_by", "unassigned_by"
    )
    return (
        jobs.select_related("customer", "source_quotation")
        .prefetch_related(
            Prefetch("assignments", queryset=assignments),
            "status_history__actor",
            "due_date_history__actor",
            "notes__author",
            "material_issues__actor",
            "material_issues__lines",
        )
        .order_by("-created_at", "id")
    )


def _job_response(organization_id, membership, user, job_id, status=200):
    job = _jobs_for_member(organization_id, membership, user).filter(pk=job_id).first()
    if job is None:
        return JsonResponse({"detail": "Job not found."}, status=404)
    return JsonResponse(JobSerializer(job).data, status=status)


@require_http_methods(["GET"])
def jobs_view(request, organization_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error
    jobs = _jobs_for_member(organization_id, membership, request.user)
    return JsonResponse({"results": JobSerializer(jobs, many=True).data})


@require_http_methods(["GET", "PATCH"])
def job_detail_view(request, organization_id, job_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error
    if request.method == "GET":
        return _job_response(organization_id, membership, request.user, job_id)
    if membership.role not in JOB_MANAGERS:
        return JsonResponse(
            {"detail": "You do not have permission to update jobs."}, status=403
        )
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    if not isinstance(payload, dict) or not payload:
        return JsonResponse({"detail": "Provide a job status or due date."}, status=400)
    if set(payload) - {"status", "due_date", "note"}:
        return JsonResponse(
            {"detail": "Only status, due date, and status note can be updated."},
            status=400,
        )
    serializer = JobUpdateSerializer(data=payload)
    try:
        serializer.is_valid(raise_exception=True)
    except ValidationError as validation_error:
        return JsonResponse(validation_error.detail, status=400)
    values = serializer.validated_data
    with transaction.atomic():
        job = (
            Job.objects.filter(organization_id=organization_id, id=job_id)
            .select_for_update()
            .first()
        )
        if job is None:
            return JsonResponse({"detail": "Job not found."}, status=404)
        update_fields = []
        if "status" in values and values["status"] != job.status:
            if values["status"] not in JOB_TRANSITIONS.get(job.status, set()):
                return JsonResponse(
                    {
                        "detail": f"Cannot move a {job.status} job to {values['status']}."
                    },
                    status=409,
                )
            previous_status = job.status
            job.status = values["status"]
            update_fields.append("status")
            JobStatusHistory.objects.create(
                job=job,
                previous_status=previous_status,
                status=job.status,
                actor=request.user,
                note=payload.get("note", "")[:240]
                if isinstance(payload.get("note", ""), str)
                else "",
            )
        if "due_date" in values and values["due_date"] != job.due_date:
            previous_due_date = job.due_date
            job.due_date = values["due_date"]
            update_fields.append("due_date")
            JobDueDateHistory.objects.create(
                job=job,
                previous_due_date=previous_due_date,
                due_date=job.due_date,
                actor=request.user,
            )
        if update_fields:
            job.save(update_fields=update_fields)
    return _job_response(organization_id, membership, request.user, job_id)


@require_http_methods(["POST"])
def job_assignment_create_view(request, organization_id, job_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error
    if membership.role not in JOB_MANAGERS:
        return JsonResponse(
            {"detail": "You do not have permission to assign jobs."}, status=403
        )
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    serializer = JobAssignmentCreateSerializer(data=payload)
    try:
        serializer.is_valid(raise_exception=True)
    except ValidationError as validation_error:
        return JsonResponse(validation_error.detail, status=400)
    username = serializer.validated_data["username"]
    user_model = get_user_model()
    assignee = user_model.objects.filter(
        username=username,
        organization_memberships__organization_id=organization_id,
    ).first()
    if assignee is None:
        return JsonResponse(
            {"username": ["Choose a user who belongs to this organization."]},
            status=400,
        )
    try:
        with transaction.atomic():
            job = (
                Job.objects.filter(organization_id=organization_id, id=job_id)
                .select_for_update()
                .first()
            )
            if job is None:
                return JsonResponse({"detail": "Job not found."}, status=404)
            assignment, created = JobAssignment.objects.get_or_create(
                job=job,
                user=assignee,
                unassigned_at__isnull=True,
                defaults={"assigned_by": request.user},
            )
            if not created:
                return _job_response(organization_id, membership, request.user, job_id)
    except IntegrityError:
        return JsonResponse(
            {"detail": "This member was assigned by another request."}, status=409
        )
    return _job_response(organization_id, membership, request.user, job_id)


@require_http_methods(["POST"])
def job_assignment_remove_view(request, organization_id, job_id, assignment_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error
    if membership.role not in JOB_MANAGERS:
        return JsonResponse(
            {"detail": "You do not have permission to update job assignments."},
            status=403,
        )
    with transaction.atomic():
        job = (
            Job.objects.filter(organization_id=organization_id, id=job_id)
            .select_for_update()
            .first()
        )
        if job is None:
            return JsonResponse({"detail": "Job not found."}, status=404)
        assignment = (
            JobAssignment.objects.filter(job=job, id=assignment_id)
            .select_for_update()
            .first()
        )
        if assignment is None:
            return JsonResponse({"detail": "Assignment not found."}, status=404)
        if assignment.unassigned_at is None:
            assignment.unassigned_at = timezone.now()
            assignment.unassigned_by = request.user
            assignment.save(update_fields=["unassigned_at", "unassigned_by"])
    return _job_response(organization_id, membership, request.user, job_id)


@require_http_methods(["POST"])
def job_note_create_view(request, organization_id, job_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    serializer = JobNoteCreateSerializer(data=payload)
    try:
        serializer.is_valid(raise_exception=True)
    except ValidationError as validation_error:
        return JsonResponse(validation_error.detail, status=400)
    with transaction.atomic():
        job = (
            _jobs_for_member(organization_id, membership, request.user)
            .filter(id=job_id)
            .first()
        )
        if job is None:
            return JsonResponse({"detail": "Job not found."}, status=404)
        if membership.role not in JOB_MANAGERS:
            assigned = JobAssignment.objects.filter(
                job=job,
                user=request.user,
                unassigned_at__isnull=True,
            ).exists()
            if membership.role != Membership.Role.EMPLOYEE or not assigned:
                return JsonResponse(
                    {"detail": "You do not have permission to add job notes."},
                    status=403,
                )
        JobNote.objects.create(
            job=job, author=request.user, content=serializer.validated_data["content"]
        )
    return _job_response(organization_id, membership, request.user, job_id)


@require_http_methods(["GET", "POST"])
def job_time_entries_view(request, organization_id, job_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error
    if membership.role not in JOB_MANAGERS | {Membership.Role.EMPLOYEE}:
        return JsonResponse(
            {"detail": "You do not have permission to access job time entries."},
            status=403,
        )
    job = Job.objects.filter(organization_id=organization_id, id=job_id).first()
    if job is None:
        return JsonResponse({"detail": "Job not found."}, status=404)
    assigned = JobAssignment.objects.filter(
        job=job, user=request.user, unassigned_at__isnull=True
    ).exists()
    if membership.role == Membership.Role.EMPLOYEE and not assigned:
        return JsonResponse({"detail": "Job not found."}, status=404)

    if request.method == "GET":
        entries = _time_entry_query(job, membership, request.user)
        return JsonResponse(
            {"results": JobTimeEntrySerializer(entries, many=True).data}
        )

    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    serializer = JobTimeEntryWriteSerializer(data=payload)
    try:
        serializer.is_valid(raise_exception=True)
    except ValidationError as validation_error:
        return JsonResponse(validation_error.detail, status=400)
    values = serializer.validated_data
    with transaction.atomic():
        job = (
            Job.objects.filter(organization_id=organization_id, id=job_id)
            .select_for_update()
            .first()
        )
        if job is None:
            return JsonResponse({"detail": "Job not found."}, status=404)
        assigned = JobAssignment.objects.filter(
            job=job, user=request.user, unassigned_at__isnull=True
        ).exists()
        if not assigned:
            return JsonResponse(
                {"detail": "You must be assigned to this job to submit time."},
                status=403,
            )
        if job.status == Job.Status.CANCELLED:
            return JsonResponse(
                {"detail": "Time cannot be submitted for a cancelled job."},
                status=409,
            )
        entry = JobTimeEntry.objects.create(
            job=job,
            employee=request.user,
            work_date=values["work_date"],
            hours=values["hours"],
            description=values.get("description", ""),
        )
        _record_time_entry_history(entry, "", request.user)
    entries = _time_entry_query(job, membership, request.user)
    return JsonResponse(
        {"results": JobTimeEntrySerializer(entries, many=True).data}, status=201
    )


@require_http_methods(["POST"])
def job_time_entry_review_view(request, organization_id, job_id, entry_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error
    if membership.role not in JOB_MANAGERS:
        return JsonResponse(
            {"detail": "You do not have permission to review job time entries."},
            status=403,
        )
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    serializer = JobTimeEntryReviewSerializer(data=payload)
    try:
        serializer.is_valid(raise_exception=True)
    except ValidationError as validation_error:
        return JsonResponse(validation_error.detail, status=400)
    values = serializer.validated_data
    with transaction.atomic():
        job = (
            Job.objects.filter(organization_id=organization_id, id=job_id)
            .select_for_update()
            .first()
        )
        if job is None:
            return JsonResponse({"detail": "Time entry not found."}, status=404)
        entry = (
            JobTimeEntry.objects.filter(
                job_id=job_id,
                job__organization_id=organization_id,
                id=entry_id,
            )
            .select_for_update()
            .first()
        )
        if entry is None:
            return JsonResponse({"detail": "Time entry not found."}, status=404)
        if entry.status != JobTimeEntry.Status.SUBMITTED:
            return JsonResponse(
                {"detail": "Only submitted time entries can be reviewed."}, status=409
            )
        previous_status = entry.status
        entry.status = (
            JobTimeEntry.Status.APPROVED
            if values["action"] == "approve"
            else JobTimeEntry.Status.REJECTED
        )
        entry.save(update_fields=["status", "updated_at"])
        _record_time_entry_history(
            entry,
            previous_status,
            request.user,
            reason=values.get("reason", ""),
        )
    entry = (
        JobTimeEntry.objects.select_related("employee")
        .prefetch_related("history__actor")
        .get(pk=entry_id)
    )
    return JsonResponse(JobTimeEntrySerializer(entry).data)


@require_http_methods(["POST"])
def job_time_entry_resubmit_view(request, organization_id, job_id, entry_id):
    membership, error = _membership(request, organization_id)
    if error:
        return error
    if membership.role not in JOB_MANAGERS | {Membership.Role.EMPLOYEE}:
        return JsonResponse(
            {"detail": "You do not have permission to update this time entry."},
            status=403,
        )
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    serializer = JobTimeEntryWriteSerializer(data=payload)
    try:
        serializer.is_valid(raise_exception=True)
    except ValidationError as validation_error:
        return JsonResponse(validation_error.detail, status=400)
    values = serializer.validated_data
    with transaction.atomic():
        job = (
            Job.objects.filter(organization_id=organization_id, id=job_id)
            .select_for_update()
            .first()
        )
        if job is None:
            return JsonResponse({"detail": "Time entry not found."}, status=404)
        entry = (
            JobTimeEntry.objects.filter(
                job_id=job_id,
                job__organization_id=organization_id,
                id=entry_id,
                employee=request.user,
            )
            .select_for_update()
            .first()
        )
        if entry is None:
            return JsonResponse({"detail": "Time entry not found."}, status=404)
        if entry.status != JobTimeEntry.Status.REJECTED:
            return JsonResponse(
                {"detail": "Only rejected time entries can be resubmitted."},
                status=409,
            )
        if entry.job.status == Job.Status.CANCELLED:
            return JsonResponse(
                {"detail": "Time cannot be submitted for a cancelled job."},
                status=409,
            )
        if not JobAssignment.objects.filter(
            job=job, user=request.user, unassigned_at__isnull=True
        ).exists():
            return JsonResponse({"detail": "Time entry not found."}, status=404)
        previous_status = entry.status
        entry.work_date = values["work_date"]
        entry.hours = values["hours"]
        entry.description = values.get("description", "")
        entry.status = JobTimeEntry.Status.SUBMITTED
        entry.save(
            update_fields=["work_date", "hours", "description", "status", "updated_at"]
        )
        _record_time_entry_history(
            entry,
            previous_status,
            request.user,
            reason="Corrected and resubmitted",
        )
    entry = (
        JobTimeEntry.objects.select_related("employee")
        .prefetch_related("history__actor")
        .get(pk=entry_id)
    )
    return JsonResponse(JobTimeEntrySerializer(entry).data)
