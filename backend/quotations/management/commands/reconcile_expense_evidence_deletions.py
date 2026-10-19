from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from quotations.deletion_ledger import (
    DeletionLedgerError,
    LocalSyntheticEvidenceDeletionLedger,
)
from quotations.evidence import EvidenceError, PrivateLocalEvidenceStorage
from quotations.evidence_deletion import (
    finish_evidence_deletion,
    replay_deletion_intent,
)
from quotations.models import ExpenseClaimEvidence, ExpenseEvidenceAuditEvent


class Command(BaseCommand):
    help = (
        "Dry-run or replay the local synthetic expense-evidence deletion journal "
        "while evidence access is disabled."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Replay deletion intents and purge matching local evidence objects.",
        )

    def handle(self, *args, **options):
        if (
            not settings.DEBUG
            or not settings.EXPENSE_EVIDENCE_LOCAL_HOSTS_ALLOWED
            or settings.EXPENSE_EVIDENCE_ENABLED
        ):
            raise CommandError(
                "Reconciliation requires local DEBUG mode with evidence access disabled."
            )
        ledger = LocalSyntheticEvidenceDeletionLedger()
        storage = PrivateLocalEvidenceStorage()
        try:
            intents = ledger.intents()
            intent_ids = {item["evidence_id"] for item in intents}
            rows_without_intent = list(
                ExpenseClaimEvidence.objects.filter(
                    state__in=[
                        ExpenseClaimEvidence.State.DELETION_PENDING,
                        ExpenseClaimEvidence.State.DELETED,
                    ]
                )
                .exclude(pk__in=intent_ids)
                .values_list("pk", flat=True)
            )
            present = sum(storage.exists(item["storage_key"]) for item in intents)
            rows_present = sum(
                ExpenseClaimEvidence.objects.filter(pk=item["evidence_id"]).exists()
                for item in intents
            )
        except (DeletionLedgerError, EvidenceError, OSError) as error:
            raise CommandError(str(error)) from error

        if not options["apply"]:
            self.stdout.write(
                "DRY RUN: found "
                f"{len(intents)} deletion intent(s), {present} object(s) present, "
                f"{rows_present} matching evidence ID(s), and "
                f"{len(rows_without_intent)} pending/deleted row(s) without an intent. "
                "Pass --apply to replay."
            )
            return

        reconciled = 0
        failures = 0
        for intent in intents:
            try:
                replay_deletion_intent(intent)
                reconciled += 1
            except (DeletionLedgerError, EvidenceError, OSError):
                failures += 1
        for evidence_id in rows_without_intent:
            try:
                finish_evidence_deletion(
                    evidence_id,
                    reason_code="pending_retry",
                    action=ExpenseEvidenceAuditEvent.Action.DELETE,
                )
                reconciled += 1
            except (DeletionLedgerError, EvidenceError, OSError):
                failures += 1

        self.stdout.write(
            f"Replayed {reconciled} deletion intent(s); {failures} need retry."
        )
        if failures:
            raise CommandError(
                "Evidence remains disabled; resolve journal or storage failures and retry."
            )
