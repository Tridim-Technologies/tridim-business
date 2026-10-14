from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from quotations.evidence import EvidenceError, PrivateLocalEvidenceStorage
from quotations.models import ExpenseClaimEvidence, ExpenseEvidenceAuditEvent


class Command(BaseCommand):
    help = "Remove stale quarantined/rejected expense evidence and retry tombstones."

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(
            seconds=settings.EXPENSE_EVIDENCE_QUARANTINE_SECONDS
        )
        candidates = ExpenseClaimEvidence.objects.filter(
            Q(state=ExpenseClaimEvidence.State.DELETED)
            | Q(
                state__in=[
                    ExpenseClaimEvidence.State.QUARANTINED,
                    ExpenseClaimEvidence.State.REJECTED,
                ],
                created_at__lt=cutoff,
            )
        )
        storage = PrivateLocalEvidenceStorage()
        removed = 0
        for candidate in candidates.iterator():
            try:
                if (
                    candidate.state == ExpenseClaimEvidence.State.DELETED
                    and not storage.exists(candidate.storage_key)
                ):
                    continue
                storage.delete(candidate.storage_key)
            except (EvidenceError, OSError):
                self.stderr.write("Could not purge a private evidence object.")
                continue
            with transaction.atomic():
                evidence = ExpenseClaimEvidence.objects.select_for_update().get(
                    pk=candidate.pk
                )
                if evidence.state != ExpenseClaimEvidence.State.DELETED:
                    evidence.state = ExpenseClaimEvidence.State.DELETED
                    evidence.deleted_at = timezone.now()
                    evidence.save(update_fields=["state", "deleted_at"])
                    ExpenseEvidenceAuditEvent.objects.create(
                        organization_id=evidence.organization_id,
                        claim=evidence.claim,
                        evidence=evidence,
                        actor=None,
                        action=ExpenseEvidenceAuditEvent.Action.DELETE,
                        outcome="purged",
                    )
            removed += 1
        self.stdout.write(f"Purged {removed} expense evidence object(s).")
