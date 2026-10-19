from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from quotations.deletion_ledger import DeletionLedgerError
from quotations.evidence import EvidenceError
from quotations.evidence_deletion import finish_evidence_deletion, mark_deletion_pending
from quotations.models import ExpenseClaimEvidence, ExpenseEvidenceAuditEvent


class Command(BaseCommand):
    help = "Remove stale quarantined/rejected expense evidence and retry tombstones."

    def handle(self, *args, **options):
        if not settings.DEBUG or not settings.EXPENSE_EVIDENCE_ENABLED:
            raise CommandError(
                "Evidence cleanup is limited to the gated local synthetic-data configuration."
            )
        cutoff = timezone.now() - timedelta(
            seconds=settings.EXPENSE_EVIDENCE_QUARANTINE_SECONDS
        )
        candidates = ExpenseClaimEvidence.objects.filter(
            Q(state=ExpenseClaimEvidence.State.DELETED)
            | Q(state=ExpenseClaimEvidence.State.DELETION_PENDING)
            | Q(
                state__in=[
                    ExpenseClaimEvidence.State.QUARANTINED,
                    ExpenseClaimEvidence.State.REJECTED,
                ],
                created_at__lt=cutoff,
            )
        )
        removed = 0
        failures = 0
        for candidate in candidates.iterator():
            with transaction.atomic():
                evidence = (
                    ExpenseClaimEvidence.objects.select_for_update()
                    .filter(pk=candidate.pk)
                    .first()
                )
                if evidence is None:
                    continue
                if (
                    evidence.state
                    in {
                        ExpenseClaimEvidence.State.QUARANTINED,
                        ExpenseClaimEvidence.State.REJECTED,
                    }
                    and evidence.created_at >= cutoff
                ):
                    continue
                if evidence.state not in {
                    ExpenseClaimEvidence.State.QUARANTINED,
                    ExpenseClaimEvidence.State.REJECTED,
                    ExpenseClaimEvidence.State.DELETION_PENDING,
                    ExpenseClaimEvidence.State.DELETED,
                }:
                    continue
                if evidence.state == ExpenseClaimEvidence.State.QUARANTINED:
                    reason_code = "quarantine_expiry"
                elif evidence.state == ExpenseClaimEvidence.State.REJECTED:
                    reason_code = "rejected_cleanup"
                else:
                    reason_code = "deletion_retry"
                mark_deletion_pending(
                    evidence,
                    action=ExpenseEvidenceAuditEvent.Action.DELETE,
                    reason_code=reason_code,
                )

            try:
                finish_evidence_deletion(
                    evidence.pk,
                    reason_code=reason_code,
                    action=ExpenseEvidenceAuditEvent.Action.DELETE,
                )
            except (DeletionLedgerError, EvidenceError, OSError):
                self.stderr.write("Could not safely purge a private evidence object.")
                failures += 1
                continue
            removed += 1
        self.stdout.write(
            f"Purged {removed} expense evidence object(s); {failures} need retry."
        )
        if failures:
            raise CommandError(
                "Some evidence remains inaccessible and needs cleanup retry."
            )
