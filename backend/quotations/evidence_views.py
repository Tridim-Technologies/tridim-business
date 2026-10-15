from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .evidence import (
    ClamAVUnixScanner,
    EvidenceError,
    EvidenceScannerUnavailable,
    PrivateLocalEvidenceStorage,
    content_digest,
    read_upload,
    validate_content,
)
from .expense_serializers import ExpenseClaimEvidenceSerializer
from .job_views import JOB_MANAGERS, _membership
from .models import (
    ExpenseClaim,
    ExpenseClaimEvidence,
    ExpenseEvidenceAuditEvent,
)


def _audit(claim, evidence, actor, action, outcome):
    ExpenseEvidenceAuditEvent.objects.create(
        organization_id=claim.organization_id,
        claim=claim,
        evidence=evidence,
        actor=actor,
        action=action,
        outcome=outcome,
    )


def _visible_claim(organization_id, claim_id, membership, user, *, lock=False):
    claims = ExpenseClaim.objects.filter(
        organization_id=organization_id, job__organization_id=organization_id
    )
    if lock:
        claims = claims.select_for_update()
    claim = claims.filter(pk=claim_id).first()
    if claim is None:
        return None
    if claim.claimant_id == user.pk:
        return claim
    if membership.role in JOB_MANAGERS:
        return claim
    return None


def _can_read(claim, membership, user):
    return claim.claimant_id == user.pk or membership.role in JOB_MANAGERS


def _target_version(claim):
    if claim.status == ExpenseClaim.Status.DRAFT:
        return claim.version
    if claim.status == ExpenseClaim.Status.RETURNED:
        return claim.version + 1
    return None


def _delete_storage_object(storage_key):
    try:
        PrivateLocalEvidenceStorage().delete(storage_key)
    except (EvidenceError, OSError):
        # The tombstone stays inaccessible; the cleanup command retries removal.
        return


def _evidence_rows(claim):
    return ExpenseClaimEvidence.objects.filter(
        claim=claim, organization_id=claim.organization_id
    )


@require_http_methods(["GET", "POST"])
def expense_claim_evidence_view(request, organization_id, claim_id):
    if not settings.EXPENSE_EVIDENCE_ENABLED:
        return JsonResponse(
            {"detail": "Evidence uploads are currently disabled."}, status=404
        )
    membership, error = _membership(request, organization_id)
    if error:
        return error

    content_length = request.META.get("CONTENT_LENGTH")
    if request.method == "POST" and content_length:
        try:
            if int(content_length) > settings.EXPENSE_EVIDENCE_MAX_FILE_BYTES + 65536:
                return JsonResponse(
                    {"file": ["Request exceeds the upload limit."]}, status=413
                )
        except ValueError:
            return JsonResponse({"detail": "Invalid request size."}, status=400)

    if request.method == "GET":
        claim = _visible_claim(organization_id, claim_id, membership, request.user)
        if claim is None or not _can_read(claim, membership, request.user):
            return JsonResponse({"detail": "Claim not found."}, status=404)
        return JsonResponse(
            {
                "results": ExpenseClaimEvidenceSerializer(
                    _evidence_rows(claim), many=True
                ).data
            }
        )

    upload = request.FILES.get("file")
    if upload is None:
        return JsonResponse({"file": ["Select a receipt file."]}, status=400)
    revision = request.POST.get("revision", "")
    try:
        revision = int(revision)
    except (TypeError, ValueError):
        return JsonResponse(
            {"revision": ["A current claim revision is required."]}, status=400
        )

    storage = PrivateLocalEvidenceStorage()
    scan_outcome = None
    with transaction.atomic():
        claim = _visible_claim(
            organization_id, claim_id, membership, request.user, lock=True
        )
        if claim is None or claim.claimant_id != request.user.pk:
            return JsonResponse({"detail": "Claim not found."}, status=404)
        if claim.revision != revision:
            return JsonResponse(
                {"detail": "Claim changed; refresh and retry."}, status=409
            )
        version = _target_version(claim)
        if version is None:
            return JsonResponse(
                {"detail": "Evidence cannot be added to this claim state."}, status=409
            )
        try:
            content = read_upload(upload)
            media_type = validate_content(upload.name, upload.content_type, content)
        except EvidenceError as error:
            return JsonResponse({"file": [str(error)]}, status=400)
        except Exception:
            return JsonResponse(
                {"file": ["File could not be safely validated."]}, status=400
            )
        existing = _evidence_rows(claim).exclude(
            state=ExpenseClaimEvidence.State.DELETED
        )
        version_count = existing.filter(claim_version=version).count()
        total_bytes = sum(existing.values_list("size_bytes", flat=True))
        if version_count >= settings.EXPENSE_EVIDENCE_MAX_FILES_PER_VERSION:
            return JsonResponse(
                {"file": ["This claim version has reached its file limit."]}, status=400
            )
        if total_bytes + len(content) > settings.EXPENSE_EVIDENCE_MAX_TOTAL_BYTES:
            return JsonResponse(
                {"file": ["This claim has reached its total evidence size limit."]},
                status=400,
            )

        try:
            storage_key = storage.put(content)
        except (OSError, EvidenceError):
            return JsonResponse(
                {"detail": "Private evidence storage is unavailable."}, status=503
            )
        evidence = ExpenseClaimEvidence.objects.create(
            organization_id=organization_id,
            claim=claim,
            claim_version=version,
            storage_key=storage_key,
            state=ExpenseClaimEvidence.State.QUARANTINED,
            detected_media_type=media_type,
            size_bytes=len(content),
            sha256=content_digest(content),
            uploaded_by=request.user,
        )
        _audit(
            claim,
            evidence,
            request.user,
            ExpenseEvidenceAuditEvent.Action.QUARANTINE,
            "stored",
        )
        try:
            clean = ClamAVUnixScanner().scan(content)
        except EvidenceScannerUnavailable:
            _audit(
                claim,
                evidence,
                request.user,
                ExpenseEvidenceAuditEvent.Action.SCAN_ERROR,
                "unavailable",
            )
            scan_outcome = "unavailable"
        except Exception:
            _audit(
                claim,
                evidence,
                request.user,
                ExpenseEvidenceAuditEvent.Action.SCAN_ERROR,
                "error",
            )
            scan_outcome = "unavailable"
        else:
            if clean:
                evidence.state = ExpenseClaimEvidence.State.ACCEPTED
                evidence.accepted_at = timezone.now()
                evidence.save(update_fields=["state", "accepted_at"])
                _audit(
                    claim,
                    evidence,
                    request.user,
                    ExpenseEvidenceAuditEvent.Action.SCAN_CLEAN,
                    "accepted",
                )
                scan_outcome = "accepted"
            else:
                evidence.state = ExpenseClaimEvidence.State.REJECTED
                evidence.save(update_fields=["state"])
                _audit(
                    claim,
                    evidence,
                    request.user,
                    ExpenseEvidenceAuditEvent.Action.SCAN_REJECTED,
                    "rejected",
                )
                scan_outcome = "rejected"

    if scan_outcome == "unavailable":
        return JsonResponse(
            {
                "detail": "Malware scanner unavailable; the quarantined file is not usable."
            },
            status=503,
        )
    if scan_outcome == "rejected":
        return JsonResponse(
            {"detail": "File failed malware scanning and cannot be attached."},
            status=400,
        )
    return JsonResponse(ExpenseClaimEvidenceSerializer(evidence).data, status=201)


@require_http_methods(["GET", "DELETE"])
def expense_claim_evidence_detail_view(request, organization_id, claim_id, evidence_id):
    if not settings.EXPENSE_EVIDENCE_ENABLED:
        return JsonResponse(
            {"detail": "Evidence uploads are currently disabled."}, status=404
        )
    membership, error = _membership(request, organization_id)
    if error:
        return error

    if request.method == "DELETE":
        with transaction.atomic():
            claim = _visible_claim(
                organization_id, claim_id, membership, request.user, lock=True
            )
            if claim is None or not _can_read(claim, membership, request.user):
                return JsonResponse({"detail": "Evidence not found."}, status=404)
            evidence = (
                _evidence_rows(claim).select_for_update().filter(pk=evidence_id).first()
            )
            if evidence is None:
                return JsonResponse({"detail": "Evidence not found."}, status=404)
            if (
                claim.claimant_id != request.user.pk
                or _target_version(claim) != evidence.claim_version
                or evidence.state != ExpenseClaimEvidence.State.ACCEPTED
            ):
                return JsonResponse({"detail": "Evidence not found."}, status=404)
            evidence.state = ExpenseClaimEvidence.State.DELETED
            evidence.deleted_at = timezone.now()
            evidence.save(update_fields=["state", "deleted_at"])
            _audit(
                claim,
                evidence,
                request.user,
                ExpenseEvidenceAuditEvent.Action.DELETE,
                "deleted",
            )
            transaction.on_commit(lambda: _delete_storage_object(evidence.storage_key))
        return JsonResponse(
            {"detail": "Evidence removed from this editable claim version."}
        )

    claim = _visible_claim(organization_id, claim_id, membership, request.user)
    if claim is None or not _can_read(claim, membership, request.user):
        return JsonResponse({"detail": "Evidence not found."}, status=404)
    evidence = _evidence_rows(claim).filter(pk=evidence_id).first()
    if evidence is None:
        return JsonResponse({"detail": "Evidence not found."}, status=404)

    if evidence.state != ExpenseClaimEvidence.State.ACCEPTED:
        return JsonResponse({"detail": "Evidence not found."}, status=404)
    try:
        content = PrivateLocalEvidenceStorage().get(evidence.storage_key)
    except EvidenceError:
        return JsonResponse({"detail": "Evidence is unavailable."}, status=404)
    if content_digest(content) != evidence.sha256:
        return JsonResponse({"detail": "Evidence integrity check failed."}, status=503)
    _audit(
        claim,
        evidence,
        request.user,
        ExpenseEvidenceAuditEvent.Action.DOWNLOAD,
        "allowed",
    )
    extension = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "application/pdf": ".pdf",
    }[evidence.detected_media_type]
    response = HttpResponse(content, content_type=evidence.detected_media_type)
    response["Content-Disposition"] = (
        f'attachment; filename="evidence-{str(evidence.pk)[:8]}{extension}"'
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Frame-Options"] = "DENY"
    response["Content-Security-Policy"] = "sandbox"
    response["Cache-Control"] = "private, no-store"
    return response
