from datetime import UTC

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from quotations.deletion_ledger import DeletionLedgerError
from quotations.evidence import EvidenceError
from quotations.evidence_deletion import finish_evidence_deletion, mark_deletion_pending
from quotations.models import ExpenseClaimEvidence, ExpenseEvidenceAuditEvent


class Command(BaseCommand):
    help = (
        "Dry-run or apply an explicit accepted-evidence expiry cutoff "
        "for local synthetic development data."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--accepted-before",
            required=True,
            help="Timezone-aware ISO 8601 cutoff; no default retention period is used.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply the expiry. Without this flag, the command only reports candidates.",
        )
        parser.add_argument(
            "--reason",
            help="Brief non-sensitive reason for the expiry; required with --apply.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG or not settings.EXPENSE_EVIDENCE_ENABLED:
            raise CommandError(
                "Evidence expiry is limited to the gated local synthetic-data configuration."
            )

        cutoff = parse_datetime(options["accepted_before"])
        if cutoff is None or timezone.is_naive(cutoff):
            raise CommandError(
                "--accepted-before must be a timezone-aware ISO 8601 datetime."
            )
        cutoff = cutoff.astimezone(UTC)
        if cutoff >= timezone.now():
            raise CommandError("--accepted-before must be in the past.")
        reason = " ".join((options.get("reason") or "").split())
        if options["apply"] and not reason:
            raise CommandError("--reason is required when --apply is used.")
        if len(reason) > 240:
            raise CommandError("--reason must be 240 characters or fewer.")

        candidates = ExpenseClaimEvidence.objects.filter(
            state=ExpenseClaimEvidence.State.ACCEPTED,
            accepted_at__lt=cutoff,
        ).order_by("accepted_at", "id")
        candidate_count = candidates.count()
        candidate_bytes = candidates.aggregate(total=Sum("size_bytes"))["total"] or 0
        if not options["apply"]:
            self.stdout.write(
                "DRY RUN: would expire "
                f"{candidate_count} accepted evidence object(s) ({candidate_bytes} bytes) "
                f"accepted before {cutoff.isoformat()}. Pass --apply to mark them deleted."
            )
            return

        expired = 0
        purge_failures = 0
        for evidence_id in candidates.values_list("pk", flat=True).iterator(
            chunk_size=100
        ):
            with transaction.atomic():
                evidence = (
                    ExpenseClaimEvidence.objects.select_for_update()
                    .select_related("claim")
                    .filter(
                        pk=evidence_id,
                        state=ExpenseClaimEvidence.State.ACCEPTED,
                        accepted_at__lt=cutoff,
                    )
                    .first()
                )
                if evidence is None:
                    continue

                mark_deletion_pending(
                    evidence,
                    action=ExpenseEvidenceAuditEvent.Action.RETENTION_EXPIRE,
                    reason_code="retention_expiry",
                    audit_metadata={
                        "accepted_before": cutoff.isoformat(),
                        "reason": reason,
                    },
                )

            try:
                finish_evidence_deletion(
                    evidence_id,
                    reason_code="retention_expiry",
                    action=ExpenseEvidenceAuditEvent.Action.RETENTION_EXPIRE,
                    completed_outcome="expired",
                    audit_metadata={
                        "accepted_before": cutoff.isoformat(),
                        "reason": reason,
                    },
                )
                expired += 1
            except (DeletionLedgerError, EvidenceError, OSError):
                purge_failures += 1

        self.stdout.write(
            f"Expired {expired} accepted evidence object(s); "
            f"{purge_failures} object(s) still need cleanup."
        )
        if purge_failures:
            raise CommandError(
                "Some expired evidence remains inaccessible but could not be purged; "
                "retry cleanup_expense_evidence."
            )
