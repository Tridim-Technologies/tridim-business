"""Fail-closed deletion orchestration for local synthetic evidence."""

from django.db import transaction
from django.utils import timezone

from .deletion_ledger import DeletionLedgerError, LocalSyntheticEvidenceDeletionLedger
from .evidence import PrivateLocalEvidenceStorage
from .models import ExpenseClaimEvidence, ExpenseEvidenceAuditEvent


def mark_deletion_pending(
    evidence, *, action, reason_code, actor=None, audit_metadata=None
):
    """Commit an inaccessible state before attempting ledger or storage I/O."""
    if evidence.state not in {
        ExpenseClaimEvidence.State.DELETION_PENDING,
        ExpenseClaimEvidence.State.DELETED,
    }:
        evidence.state = ExpenseClaimEvidence.State.DELETION_PENDING
        evidence.deleted_at = timezone.now()
        evidence.save(update_fields=["state", "deleted_at"])
    if not ExpenseEvidenceAuditEvent.objects.filter(
        evidence=evidence, action=action, outcome="deletion_pending"
    ).exists():
        ExpenseEvidenceAuditEvent.objects.create(
            organization_id=evidence.organization_id,
            claim=evidence.claim,
            evidence=evidence,
            actor=actor,
            action=action,
            outcome="deletion_pending",
            metadata={"reason_code": reason_code, **(audit_metadata or {})},
        )


def _metadata_for(evidence, reason_code):
    return {
        "evidence_id": evidence.pk,
        "organization_id": evidence.organization_id,
        "claim_id": evidence.claim_id,
        "storage_key": evidence.storage_key,
        "reason_code": reason_code,
    }


def finish_evidence_deletion(
    evidence_id,
    *,
    reason_code,
    action,
    completed_outcome=None,
    audit_metadata=None,
):
    """Acknowledge intent, purge bytes, record completion, then finalize the row."""
    evidence = (
        ExpenseClaimEvidence.objects.select_related("claim")
        .filter(pk=evidence_id)
        .first()
    )
    if evidence is None:
        return False
    if evidence.state not in {
        ExpenseClaimEvidence.State.DELETION_PENDING,
        ExpenseClaimEvidence.State.DELETED,
    }:
        raise DeletionLedgerError("Evidence must be inaccessible before it is purged.")

    metadata = _metadata_for(evidence, reason_code)
    ledger = LocalSyntheticEvidenceDeletionLedger()
    storage = PrivateLocalEvidenceStorage()
    ledger.record_intent(**metadata)
    storage.delete(evidence.storage_key)
    ledger.record_purged(**metadata)

    with transaction.atomic():
        current = (
            ExpenseClaimEvidence.objects.select_for_update()
            .filter(pk=evidence.pk)
            .first()
        )
        if current is None:
            return True
        if (
            current.storage_key != evidence.storage_key
            or current.organization_id != evidence.organization_id
            or current.claim_id != evidence.claim_id
        ):
            raise DeletionLedgerError(
                "Evidence metadata changed while deletion was in progress."
            )
        update_fields = []
        if current.state != ExpenseClaimEvidence.State.DELETED:
            current.state = ExpenseClaimEvidence.State.DELETED
            update_fields.append("state")
        if current.deleted_at is None:
            current.deleted_at = timezone.now()
            update_fields.append("deleted_at")
        if update_fields:
            current.save(update_fields=update_fields)
        pending_event = (
            ExpenseEvidenceAuditEvent.objects.filter(
                evidence=current, outcome="deletion_pending"
            )
            .order_by("-created_at", "-pk")
            .first()
        )
        completed_action = pending_event.action if pending_event else action
        completed_outcome = completed_outcome or (
            "expired"
            if completed_action == ExpenseEvidenceAuditEvent.Action.RETENTION_EXPIRE
            else "purged"
        )
        completed_metadata = (
            audit_metadata
            if audit_metadata is not None
            else pending_event.metadata
            if pending_event
            else {"reason_code": reason_code}
        )
        if not ExpenseEvidenceAuditEvent.objects.filter(
            evidence=current, action=completed_action, outcome=completed_outcome
        ).exists():
            ExpenseEvidenceAuditEvent.objects.create(
                organization_id=current.organization_id,
                claim=current.claim,
                evidence=current,
                actor=pending_event.actor if pending_event else None,
                action=completed_action,
                outcome=completed_outcome,
                metadata=completed_metadata,
            )
    return True


def replay_deletion_intent(intent):
    """Re-purge an intent and tombstone a matching row if an older DB has it."""
    evidence = ExpenseClaimEvidence.objects.filter(pk=intent["evidence_id"]).first()
    if evidence is not None and (
        str(evidence.organization_id) != intent["organization_id"]
        or str(evidence.claim_id) != intent["claim_id"]
        or evidence.storage_key != intent["storage_key"]
    ):
        raise DeletionLedgerError(
            "Restored evidence metadata does not match the deletion journal."
        )
    if evidence is not None:
        with transaction.atomic():
            evidence = ExpenseClaimEvidence.objects.select_for_update().get(
                pk=evidence.pk
            )
            if (
                str(evidence.organization_id) != intent["organization_id"]
                or str(evidence.claim_id) != intent["claim_id"]
                or evidence.storage_key != intent["storage_key"]
            ):
                raise DeletionLedgerError(
                    "Restored evidence metadata does not match the deletion journal."
                )
            mark_deletion_pending(
                evidence,
                action=ExpenseEvidenceAuditEvent.Action.DELETE,
                reason_code="restore_replay",
            )

    metadata = {
        "evidence_id": intent["evidence_id"],
        "organization_id": intent["organization_id"],
        "claim_id": intent["claim_id"],
        "storage_key": intent["storage_key"],
        "reason_code": intent["reason_code"],
    }
    storage = PrivateLocalEvidenceStorage()
    storage.delete(intent["storage_key"])
    ledger = LocalSyntheticEvidenceDeletionLedger()
    ledger.record_purged(**metadata)

    if evidence is not None:
        with transaction.atomic():
            current = ExpenseClaimEvidence.objects.select_for_update().get(
                pk=evidence.pk
            )
            if (
                str(current.organization_id) != intent["organization_id"]
                or str(current.claim_id) != intent["claim_id"]
                or current.storage_key != intent["storage_key"]
            ):
                raise DeletionLedgerError(
                    "Restored evidence metadata changed during replay."
                )
            update_fields = []
            if current.state != ExpenseClaimEvidence.State.DELETED:
                current.state = ExpenseClaimEvidence.State.DELETED
                update_fields.append("state")
            if current.deleted_at is None:
                current.deleted_at = timezone.now()
                update_fields.append("deleted_at")
            if update_fields:
                current.save(update_fields=update_fields)
            if not ExpenseEvidenceAuditEvent.objects.filter(
                evidence=current,
                action=ExpenseEvidenceAuditEvent.Action.DELETE,
                outcome="restore_replayed",
            ).exists():
                ExpenseEvidenceAuditEvent.objects.create(
                    organization_id=current.organization_id,
                    claim=current.claim,
                    evidence=current,
                    actor=None,
                    action=ExpenseEvidenceAuditEvent.Action.DELETE,
                    outcome="restore_replayed",
                    metadata={"reason_code": "restore_replay"},
                )
    return evidence is not None
