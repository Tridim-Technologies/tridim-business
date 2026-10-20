import io
import os
import sqlite3
import tempfile
from datetime import UTC
from datetime import timedelta
from pathlib import Path
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from pypdf import PdfWriter

from accounts.models import Membership, Organization
from customers.models import Customer

from .deletion_ledger import (
    DeletionLedgerError,
    LocalSyntheticEvidenceDeletionLedger,
)
from .evidence_adapters import EvidenceDeletionJournal, EvidenceStorage
from .evidence_deletion import finish_evidence_deletion, mark_deletion_pending
from .models import (
    ExpenseClaim,
    ExpenseClaimEvidence,
    ExpenseEvidenceAuditEvent,
    Job,
    JobAssignment,
    Quotation,
)
from .evidence import EvidenceError, PrivateLocalEvidenceStorage


class _FailureInjectionStorage:
    def __init__(self, delegate=None, *, fail_delete=False):
        self.calls = []
        self.fail_delete = fail_delete
        self.delegate = delegate

    def put(self, content):
        self.calls.append(("put", content))
        return "synthetic-key"

    def get(self, key):
        self.calls.append(("get", key))
        return self.delegate.get(key) if self.delegate else b"synthetic"

    def delete(self, key):
        self.calls.append(("delete", key))
        if self.fail_delete:
            raise OSError("injected storage failure")
        if self.delegate:
            self.delegate.delete(key)

    def exists(self, key):
        self.calls.append(("exists", key))
        return self.delegate.exists(key) if self.delegate else True


class _FailureInjectionJournal:
    def __init__(self, *, fail_intent=False, fail_purged=False):
        self.calls = []
        self.fail_intent = fail_intent
        self.fail_purged = fail_purged

    def record_intent(self, **metadata):
        self.calls.append(("intent", metadata))
        if self.fail_intent:
            raise DeletionLedgerError("injected journal intent failure")

    def record_purged(self, **metadata):
        self.calls.append(("purged", metadata))
        if self.fail_purged:
            raise DeletionLedgerError("injected journal completion failure")

    def intents(self):
        return []


@override_settings(DEBUG=True, EXPENSE_EVIDENCE_LOCAL_HOSTS_ALLOWED=True)
class ExpenseEvidenceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="evidence-owner")
        self.employee = user_model.objects.create_user(username="evidence-employee")
        self.other = user_model.objects.create_user(username="evidence-other")
        self.finance = user_model.objects.create_user(username="evidence-finance")
        self.organization = Organization.objects.create(name="Evidence Org")
        self.other_organization = Organization.objects.create(name="Other Evidence Org")
        for user, role in (
            (self.owner, Membership.Role.OWNER),
            (self.employee, Membership.Role.EMPLOYEE),
            (self.other, Membership.Role.EMPLOYEE),
            (self.finance, Membership.Role.FINANCE),
        ):
            Membership.objects.create(
                organization=self.organization, user=user, role=role
            )
        Membership.objects.create(
            organization=self.other_organization,
            user=self.other,
            role=Membership.Role.EMPLOYEE,
        )
        customer = Customer.objects.create(
            organization=self.organization,
            name="Synthetic evidence customer",
            created_by=self.owner,
        )
        quotation = Quotation.objects.create(
            organization=self.organization,
            customer=customer,
            currency="KES",
            valid_until=timezone.localdate() + timedelta(days=7),
            created_by=self.owner,
            status=Quotation.Status.ACCEPTED,
        )
        self.job = Job.objects.create(
            organization=self.organization,
            customer=customer,
            source_quotation=quotation,
            created_by=self.owner,
        )
        JobAssignment.objects.create(
            job=self.job, user=self.employee, assigned_by=self.owner
        )
        self.claim = ExpenseClaim.objects.create(
            organization=self.organization,
            job=self.job,
            claimant=self.employee,
            expense_date=timezone.localdate(),
            amount="12.50",
            currency="KES",
            category=ExpenseClaim.Category.TRAVEL,
            purpose="Synthetic test expense",
        )
        self.storage = tempfile.TemporaryDirectory()
        self.ledger = tempfile.TemporaryDirectory()
        self.ledger_settings = override_settings(
            EXPENSE_EVIDENCE_LEDGER_ROOT=self.ledger.name
        )
        self.ledger_settings.enable()

    def tearDown(self):
        self.ledger_settings.disable()
        self.ledger.cleanup()
        self.storage.cleanup()

    def evidence_url(self, claim=None):
        return reverse(
            "expense-claim-evidence",
            args=[self.organization.pk, (claim or self.claim).pk],
        )

    def item_url(self, evidence, claim=None):
        return reverse(
            "expense-claim-evidence-detail",
            args=[self.organization.pk, (claim or self.claim).pk, evidence.pk],
        )

    def png_upload(self, name="receipt.png"):
        image = Image.new("RGB", (12, 8), color="white")
        content = io.BytesIO()
        image.save(content, format="PNG")
        return SimpleUploadedFile(name, content.getvalue(), content_type="image/png")

    def encrypted_pdf_upload(self):
        content = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.encrypt("synthetic-password")
        writer.write(content)
        return SimpleUploadedFile(
            "receipt.pdf", content.getvalue(), content_type="application/pdf"
        )

    @override_settings(EXPENSE_EVIDENCE_ENABLED=False)
    def test_feature_is_disabled_by_default(self):
        self.client.force_login(self.employee)
        response = self.client.get(self.evidence_url())
        self.assertEqual(response.status_code, 404)

    def test_storage_rejects_public_application_directories(self):
        public_path = Path(settings.BASE_DIR) / "frontend" / "public" / "evidence"
        with self.assertRaises(EvidenceError):
            PrivateLocalEvidenceStorage(public_path).put(b"synthetic")

    @override_settings(
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
    )
    @patch("quotations.evidence_views.ClamAVUnixScanner.scan", return_value=True)
    def test_clean_upload_is_private_immutable_and_downloaded_safely(self, scan):
        from django.test import override_settings as settings_override

        with settings_override(EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name):
            self.client.force_login(self.employee)
            response = self.client.post(
                self.evidence_url(),
                {"revision": str(self.claim.revision), "file": self.png_upload()},
            )
            self.assertEqual(response.status_code, 201, response.content)
            evidence = ExpenseClaimEvidence.objects.get(pk=response.json()["id"])
            self.assertEqual(evidence.state, ExpenseClaimEvidence.State.ACCEPTED)
            self.assertEqual(evidence.detected_media_type, "image/png")
            self.assertNotIn("original_name", response.json())
            path = os.path.join(self.storage.name, f"{evidence.storage_key}.evidence")
            self.assertEqual(os.stat(self.storage.name).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            download = self.client.get(self.item_url(evidence))
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download["X-Content-Type-Options"], "nosniff")
            self.assertEqual(download["Cache-Control"], "private, no-store")
            self.assertIn("attachment;", download["Content-Disposition"])
            self.assertNotIn("receipt.png", download["Content-Disposition"])
            self.assertEqual(
                ExpenseEvidenceAuditEvent.objects.filter(
                    evidence=evidence, action=ExpenseEvidenceAuditEvent.Action.DOWNLOAD
                ).count(),
                1,
            )
            scan.assert_called_once()

    @override_settings(
        DEBUG=True,
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
    )
    @patch(
        "quotations.evidence_views.ClamAVUnixScanner.scan",
        side_effect=Exception("scanner detail must not be returned"),
    )
    def test_scanner_error_fails_closed_and_leaves_quarantine(self, _scan):
        from django.test import override_settings as settings_override

        with settings_override(EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name):
            self.client.force_login(self.employee)
            response = self.client.post(
                self.evidence_url(),
                {"revision": str(self.claim.revision), "file": self.png_upload()},
            )
            self.assertEqual(response.status_code, 503)
            self.assertNotIn(b"scanner detail", response.content)
            evidence = ExpenseClaimEvidence.objects.get()
            self.assertEqual(evidence.state, ExpenseClaimEvidence.State.QUARANTINED)
            self.assertEqual(self.client.get(self.item_url(evidence)).status_code, 404)
            self.assertTrue(
                os.path.exists(
                    os.path.join(self.storage.name, f"{evidence.storage_key}.evidence")
                )
            )
            self.assertTrue(
                ExpenseEvidenceAuditEvent.objects.filter(
                    evidence=evidence,
                    action=ExpenseEvidenceAuditEvent.Action.SCAN_ERROR,
                    outcome="error",
                ).exists()
            )

    @override_settings(
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
    )
    @patch("quotations.evidence_views.ClamAVUnixScanner.scan", return_value=False)
    def test_malware_result_is_rejected_and_not_downloadable(self, _scan):
        from django.test import override_settings as settings_override

        with settings_override(EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name):
            self.client.force_login(self.employee)
            response = self.client.post(
                self.evidence_url(),
                {"revision": str(self.claim.revision), "file": self.png_upload()},
            )
            self.assertEqual(response.status_code, 400)
            evidence = ExpenseClaimEvidence.objects.get()
            self.assertEqual(evidence.state, ExpenseClaimEvidence.State.REJECTED)
            self.assertEqual(self.client.get(self.item_url(evidence)).status_code, 404)

    @override_settings(
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
    )
    @patch("quotations.evidence_views.ClamAVUnixScanner.scan", return_value=True)
    def test_claimant_can_delete_draft_evidence_with_audited_tombstone(self, _scan):
        from django.test import override_settings as settings_override

        with settings_override(EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name):
            self.client.force_login(self.employee)
            response = self.client.post(
                self.evidence_url(),
                {"revision": str(self.claim.revision), "file": self.png_upload()},
            )
            evidence = ExpenseClaimEvidence.objects.get(pk=response.json()["id"])
            path = os.path.join(self.storage.name, f"{evidence.storage_key}.evidence")
            self.assertTrue(os.path.exists(path))
            with self.captureOnCommitCallbacks(execute=True):
                deleted = self.client.delete(self.item_url(evidence))
            self.assertEqual(deleted.status_code, 200, deleted.content)
            evidence.refresh_from_db()
            self.assertEqual(evidence.state, ExpenseClaimEvidence.State.DELETED)
            self.assertFalse(os.path.exists(path))
            self.assertTrue(
                ExpenseEvidenceAuditEvent.objects.filter(
                    evidence=evidence,
                    actor=self.employee,
                    action=ExpenseEvidenceAuditEvent.Action.DELETE,
                    outcome="purged",
                ).exists()
            )

    @override_settings(EXPENSE_EVIDENCE_ENABLED=True)
    def test_malformed_or_mismatched_content_is_rejected_before_scanning(self):
        self.client.force_login(self.employee)
        response = self.client.post(
            self.evidence_url(),
            {
                "revision": str(self.claim.revision),
                "file": SimpleUploadedFile(
                    "receipt.png", b"not a PNG", content_type="image/png"
                ),
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ExpenseClaimEvidence.objects.count(), 0)

    @override_settings(EXPENSE_EVIDENCE_ENABLED=True)
    @patch("quotations.evidence_views.ClamAVUnixScanner.scan")
    def test_encrypted_pdf_is_rejected_before_scanning(self, scan):
        self.client.force_login(self.employee)
        response = self.client.post(
            self.evidence_url(),
            {
                "revision": str(self.claim.revision),
                "file": self.encrypted_pdf_upload(),
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ExpenseClaimEvidence.objects.count(), 0)
        scan.assert_not_called()

    @override_settings(
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
    )
    @patch("quotations.evidence_views.ClamAVUnixScanner.scan", return_value=True)
    def test_cross_tenant_and_finance_roles_cannot_read_evidence(self, _scan):
        from django.test import override_settings as settings_override

        with settings_override(EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name):
            self.client.force_login(self.employee)
            response = self.client.post(
                self.evidence_url(),
                {"revision": str(self.claim.revision), "file": self.png_upload()},
            )
            evidence = ExpenseClaimEvidence.objects.get(pk=response.json()["id"])
            self.client.force_login(self.other)
            self.assertEqual(self.client.get(self.item_url(evidence)).status_code, 404)
            self.client.force_login(self.finance)
            self.assertEqual(self.client.get(self.item_url(evidence)).status_code, 404)

    @override_settings(
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
    )
    @patch("quotations.evidence_views.ClamAVUnixScanner.scan", return_value=True)
    def test_claim_version_evidence_is_append_only_after_return(self, _scan):
        from django.test import override_settings as settings_override

        with settings_override(EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name):
            self.client.force_login(self.employee)
            first = self.client.post(
                self.evidence_url(),
                {
                    "revision": str(self.claim.revision),
                    "file": self.png_upload("v1.png"),
                },
            )
            first_evidence = ExpenseClaimEvidence.objects.get(pk=first.json()["id"])
            self.claim.refresh_from_db()
            transition = reverse(
                "expense-claim-transition", args=[self.organization.pk, self.claim.pk]
            )
            self.assertEqual(
                self.client.post(
                    transition,
                    {"action": "submit", "revision": self.claim.revision},
                    content_type="application/json",
                ).status_code,
                200,
            )
            self.claim.refresh_from_db()
            self.client.force_login(self.owner)
            accepted_download = self.client.get(self.item_url(first_evidence))
            self.assertEqual(accepted_download.status_code, 200)
            self.client.force_login(self.employee)
            self.client.force_login(self.owner)
            returned = self.client.post(
                transition,
                {
                    "action": "return",
                    "revision": self.claim.revision,
                    "reason": "Synthetic correction",
                },
                content_type="application/json",
            )
            self.assertEqual(returned.status_code, 200, returned.content)
            self.claim.refresh_from_db()
            self.client.force_login(self.employee)
            second = self.client.post(
                self.evidence_url(),
                {
                    "revision": str(self.claim.revision),
                    "file": self.png_upload("v2.png"),
                },
            )
            self.assertEqual(second.status_code, 201, second.content)
            second_evidence = ExpenseClaimEvidence.objects.get(pk=second.json()["id"])
            self.assertEqual(first_evidence.claim_version, 1)
            self.assertEqual(second_evidence.claim_version, 2)
            self.claim.refresh_from_db()
            self.assertEqual(
                self.client.post(
                    transition,
                    {"action": "resubmit", "revision": self.claim.revision},
                    content_type="application/json",
                ).status_code,
                200,
            )
            self.claim.refresh_from_db()
            self.assertEqual(self.claim.version, 2)
            self.assertEqual(
                self.client.get(
                    reverse(
                        "expense-claim-detail",
                        args=[self.organization.pk, self.claim.pk],
                    )
                ).json()["receipt_state"],
                "accepted",
            )
            self.assertEqual(first_evidence.state, ExpenseClaimEvidence.State.ACCEPTED)
            self.claim.refresh_from_db()
            self.client.force_login(self.owner)
            approved = self.client.post(
                transition,
                {"action": "approve", "revision": self.claim.revision},
                content_type="application/json",
            )
            self.assertEqual(approved.status_code, 200, approved.content)
            self.assertEqual(approved.json()["status"], ExpenseClaim.Status.APPROVED)

    @override_settings(
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
        EXPENSE_EVIDENCE_QUARANTINE_SECONDS=60,
    )
    @patch(
        "quotations.evidence_views.ClamAVUnixScanner.scan",
        side_effect=Exception("scanner unavailable"),
    )
    def test_cleanup_purges_stale_quarantine_and_keeps_audit_tombstone(self, _scan):
        from django.test import override_settings as settings_override

        with settings_override(EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name):
            self.client.force_login(self.employee)
            self.client.post(
                self.evidence_url(),
                {"revision": str(self.claim.revision), "file": self.png_upload()},
            )
            evidence = ExpenseClaimEvidence.objects.get()
            evidence.created_at = timezone.now() - timedelta(minutes=2)
            evidence.save(update_fields=["created_at"])
            path = os.path.join(self.storage.name, f"{evidence.storage_key}.evidence")
            self.assertTrue(os.path.exists(path))
            call_command("cleanup_expense_evidence", verbosity=0)
            evidence.refresh_from_db()
            self.assertEqual(evidence.state, ExpenseClaimEvidence.State.DELETED)
            self.assertFalse(os.path.exists(path))
            self.assertTrue(
                ExpenseEvidenceAuditEvent.objects.filter(
                    evidence=evidence,
                    actor__isnull=True,
                    outcome="purged",
                ).exists()
            )

    def upload_accepted_evidence(self):
        self.client.force_login(self.employee)
        response = self.client.post(
            self.evidence_url(),
            {"revision": str(self.claim.revision), "file": self.png_upload()},
        )
        self.assertEqual(response.status_code, 201, response.content)
        evidence = ExpenseClaimEvidence.objects.get(pk=response.json()["id"])
        path = Path(self.storage.name) / f"{evidence.storage_key}.evidence"
        return evidence, path

    @override_settings(
        DEBUG=True,
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
    )
    @patch("quotations.evidence_views.ClamAVUnixScanner.scan", return_value=True)
    def test_deletion_adapter_contract_and_failure_injection(self, _scan):
        self.assertIsInstance(PrivateLocalEvidenceStorage(), EvidenceStorage)
        self.assertIsInstance(
            LocalSyntheticEvidenceDeletionLedger(), EvidenceDeletionJournal
        )

        with override_settings(EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name):
            evidence, path = self.upload_accepted_evidence()
            mark_deletion_pending(
                evidence,
                action=ExpenseEvidenceAuditEvent.Action.DELETE,
                reason_code="synthetic_contract_test",
            )

            storage = _FailureInjectionStorage(PrivateLocalEvidenceStorage())
            journal = _FailureInjectionJournal(fail_intent=True)
            with self.assertRaises(DeletionLedgerError):
                finish_evidence_deletion(
                    evidence.pk,
                    reason_code="synthetic_contract_test",
                    action=ExpenseEvidenceAuditEvent.Action.DELETE,
                    storage=storage,
                    journal=journal,
                )
            self.assertEqual(storage.calls, [])
            self.assertEqual([name for name, _ in journal.calls], ["intent"])
            self.assertTrue(path.exists())

            storage = _FailureInjectionStorage(
                PrivateLocalEvidenceStorage(), fail_delete=True
            )
            journal = _FailureInjectionJournal()
            with self.assertRaises(OSError):
                finish_evidence_deletion(
                    evidence.pk,
                    reason_code="synthetic_contract_test",
                    action=ExpenseEvidenceAuditEvent.Action.DELETE,
                    storage=storage,
                    journal=journal,
                )
            self.assertEqual([name for name, _ in journal.calls], ["intent"])
            self.assertEqual([name for name, _ in storage.calls], ["delete"])
            self.assertTrue(path.exists())

            storage = _FailureInjectionStorage(PrivateLocalEvidenceStorage())
            journal = _FailureInjectionJournal(fail_purged=True)
            with self.assertRaises(DeletionLedgerError):
                finish_evidence_deletion(
                    evidence.pk,
                    reason_code="synthetic_contract_test",
                    action=ExpenseEvidenceAuditEvent.Action.DELETE,
                    storage=storage,
                    journal=journal,
                )
            self.assertEqual([name for name, _ in journal.calls], ["intent", "purged"])
            self.assertFalse(path.exists())
            evidence.refresh_from_db()
            self.assertEqual(
                evidence.state, ExpenseClaimEvidence.State.DELETION_PENDING
            )

            retry_storage = _FailureInjectionStorage(PrivateLocalEvidenceStorage())
            retry_journal = _FailureInjectionJournal()
            self.assertTrue(
                finish_evidence_deletion(
                    evidence.pk,
                    reason_code="synthetic_contract_test",
                    action=ExpenseEvidenceAuditEvent.Action.DELETE,
                    storage=retry_storage,
                    journal=retry_journal,
                )
            )
            evidence.refresh_from_db()
            self.assertEqual(evidence.state, ExpenseClaimEvidence.State.DELETED)
            self.assertEqual(
                [name for name, _ in retry_journal.calls], ["intent", "purged"]
            )

    @override_settings(
        DEBUG=True,
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
    )
    @patch("quotations.evidence_views.ClamAVUnixScanner.scan", return_value=True)
    def test_delete_failure_keeps_pending_row_and_replayable_journal_intent(
        self, _scan
    ):
        with override_settings(EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name):
            evidence, path = self.upload_accepted_evidence()
            with patch(
                "quotations.evidence_deletion.PrivateLocalEvidenceStorage.delete",
                side_effect=OSError("synthetic storage failure"),
            ):
                response = self.client.delete(self.item_url(evidence))

            self.assertEqual(response.status_code, 503)
            evidence.refresh_from_db()
            self.assertEqual(
                evidence.state, ExpenseClaimEvidence.State.DELETION_PENDING
            )
            self.assertTrue(path.exists())
            self.assertEqual(self.client.get(self.item_url(evidence)).status_code, 404)
            intents = LocalSyntheticEvidenceDeletionLedger().intents()
            self.assertEqual(len(intents), 1)
            self.assertFalse(intents[0]["purged"])

            with override_settings(EXPENSE_EVIDENCE_ENABLED=False):
                call_command("reconcile_expense_evidence_deletions", apply=True)

            evidence.refresh_from_db()
            self.assertEqual(evidence.state, ExpenseClaimEvidence.State.DELETED)
            self.assertFalse(path.exists())
            self.assertTrue(
                LocalSyntheticEvidenceDeletionLedger().intents()[0]["purged"]
            )

    @override_settings(
        DEBUG=True,
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
    )
    @patch("quotations.evidence_views.ClamAVUnixScanner.scan", return_value=True)
    def test_replay_completes_when_crash_follows_byte_purge(self, _scan):
        with override_settings(EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name):
            evidence, path = self.upload_accepted_evidence()
            record_purged = LocalSyntheticEvidenceDeletionLedger.record_purged
            with patch.object(
                LocalSyntheticEvidenceDeletionLedger,
                "record_purged",
                side_effect=OSError("synthetic crash after object purge"),
            ):
                response = self.client.delete(self.item_url(evidence))

            self.assertEqual(response.status_code, 503)
            self.assertFalse(path.exists())
            evidence.refresh_from_db()
            self.assertEqual(
                evidence.state, ExpenseClaimEvidence.State.DELETION_PENDING
            )
            self.assertFalse(
                LocalSyntheticEvidenceDeletionLedger().intents()[0]["purged"]
            )

            with override_settings(EXPENSE_EVIDENCE_ENABLED=False):
                with patch.object(
                    LocalSyntheticEvidenceDeletionLedger,
                    "record_purged",
                    record_purged,
                ):
                    call_command("reconcile_expense_evidence_deletions", apply=True)

            evidence.refresh_from_db()
            self.assertEqual(evidence.state, ExpenseClaimEvidence.State.DELETED)
            self.assertTrue(
                LocalSyntheticEvidenceDeletionLedger().intents()[0]["purged"]
            )

    @override_settings(
        DEBUG=True,
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
    )
    @patch("quotations.evidence_views.ClamAVUnixScanner.scan", return_value=True)
    def test_replay_reconciles_restored_older_database_and_file_snapshots(self, _scan):
        with override_settings(EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name):
            evidence, path = self.upload_accepted_evidence()
            response = self.client.delete(self.item_url(evidence))
            self.assertEqual(response.status_code, 200, response.content)
            evidence.refresh_from_db()
            evidence.state = ExpenseClaimEvidence.State.ACCEPTED
            evidence.deleted_at = None
            evidence.save(update_fields=["state", "deleted_at"])
            path.write_bytes(b"synthetic bytes from an older object snapshot")

            with override_settings(EXPENSE_EVIDENCE_ENABLED=False):
                output = StringIO()
                call_command("reconcile_expense_evidence_deletions", stdout=output)
                self.assertIn("DRY RUN: found 1 deletion intent", output.getvalue())
                self.assertTrue(path.exists())
                evidence.refresh_from_db()
                self.assertEqual(evidence.state, ExpenseClaimEvidence.State.ACCEPTED)

                call_command("reconcile_expense_evidence_deletions", apply=True)
                call_command("reconcile_expense_evidence_deletions", apply=True)

            evidence.refresh_from_db()
            self.assertEqual(evidence.state, ExpenseClaimEvidence.State.DELETED)
            self.assertFalse(path.exists())
            intents = LocalSyntheticEvidenceDeletionLedger().intents()
            self.assertEqual(len(intents), 1)
            self.assertTrue(intents[0]["purged"])
            self.assertEqual(
                ExpenseEvidenceAuditEvent.objects.filter(
                    evidence=evidence, outcome="restore_replayed"
                ).count(),
                1,
            )

    @override_settings(
        DEBUG=True,
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
    )
    @patch("quotations.evidence_views.ClamAVUnixScanner.scan", return_value=True)
    def test_replay_purges_object_even_when_restored_database_row_is_missing(
        self, _scan
    ):
        with override_settings(EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name):
            evidence, path = self.upload_accepted_evidence()
            response = self.client.delete(self.item_url(evidence))
            self.assertEqual(response.status_code, 200, response.content)
            evidence.delete()
            path.write_bytes(b"synthetic bytes from an older object snapshot")

            with override_settings(EXPENSE_EVIDENCE_ENABLED=False):
                call_command("reconcile_expense_evidence_deletions", apply=True)

            self.assertFalse(path.exists())
            self.assertFalse(
                ExpenseClaimEvidence.objects.filter(pk=evidence.pk).exists()
            )

    @override_settings(
        DEBUG=True,
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
    )
    @patch("quotations.evidence_views.ClamAVUnixScanner.scan", return_value=True)
    def test_pending_row_without_acknowledged_intent_can_be_retried(self, _scan):
        with override_settings(EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name):
            evidence, path = self.upload_accepted_evidence()
            with patch(
                "quotations.evidence_deletion.LocalSyntheticEvidenceDeletionLedger.record_intent",
                side_effect=DeletionLedgerError("synthetic journal failure"),
            ):
                response = self.client.delete(self.item_url(evidence))
            self.assertEqual(response.status_code, 503)
            evidence.refresh_from_db()
            self.assertEqual(
                evidence.state, ExpenseClaimEvidence.State.DELETION_PENDING
            )
            self.assertTrue(path.exists())

            with override_settings(EXPENSE_EVIDENCE_ENABLED=False):
                output = StringIO()
                call_command("reconcile_expense_evidence_deletions", stdout=output)
                self.assertIn(
                    "1 pending/deleted row(s) without an intent", output.getvalue()
                )
                call_command("reconcile_expense_evidence_deletions", apply=True)

            evidence.refresh_from_db()
            self.assertEqual(evidence.state, ExpenseClaimEvidence.State.DELETED)
            self.assertFalse(path.exists())

    @override_settings(
        DEBUG=True,
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
    )
    @patch("quotations.evidence_views.ClamAVUnixScanner.scan", return_value=True)
    def test_corrupt_journal_fails_closed_without_purging_restored_bytes(self, _scan):
        with override_settings(EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name):
            evidence, path = self.upload_accepted_evidence()
            with transaction.atomic():
                evidence = ExpenseClaimEvidence.objects.select_for_update().get(
                    pk=evidence.pk
                )
                mark_deletion_pending(
                    evidence,
                    action=ExpenseEvidenceAuditEvent.Action.DELETE,
                    reason_code="synthetic_test",
                )
            ledger = LocalSyntheticEvidenceDeletionLedger()
            ledger.record_intent(
                evidence.pk,
                evidence.organization_id,
                evidence.claim_id,
                evidence.storage_key,
                "synthetic_test",
            )
            connection = sqlite3.connect(ledger.database)
            connection.execute("DROP TRIGGER deletion_event_no_update")
            connection.execute(
                "UPDATE deletion_event SET storage_key=? WHERE event_type='intent'",
                ("f" * 32,),
            )
            connection.commit()
            connection.close()

            with override_settings(EXPENSE_EVIDENCE_ENABLED=False):
                with self.assertRaisesMessage(CommandError, "integrity verification"):
                    call_command("reconcile_expense_evidence_deletions", apply=True)
            self.assertTrue(path.exists())

    def test_ledger_rejects_path_overlap_with_evidence_storage(self):
        with override_settings(
            EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name,
            EXPENSE_EVIDENCE_LEDGER_ROOT=self.storage.name,
        ):
            with self.assertRaisesMessage(
                DeletionLedgerError, "must use separate directories"
            ):
                LocalSyntheticEvidenceDeletionLedger().intents()

    @override_settings(
        DEBUG=True,
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
    )
    @patch("quotations.evidence_views.ClamAVUnixScanner.scan", return_value=True)
    def test_expiry_dry_run_reports_only_eligible_accepted_evidence(self, _scan):
        with override_settings(EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name):
            evidence, path = self.upload_accepted_evidence()
            recent_evidence, recent_path = self.upload_accepted_evidence()
            rejected_evidence, rejected_path = self.upload_accepted_evidence()
            evidence.accepted_at = timezone.now() - timedelta(days=3)
            evidence.save(update_fields=["accepted_at"])
            rejected_evidence.state = ExpenseClaimEvidence.State.REJECTED
            rejected_evidence.save(update_fields=["state"])
            cutoff = timezone.now() - timedelta(days=2)
            output = StringIO()

            call_command(
                "expire_expense_evidence",
                accepted_before=cutoff.isoformat(),
                stdout=output,
            )

            evidence.refresh_from_db()
            recent_evidence.refresh_from_db()
            rejected_evidence.refresh_from_db()
            self.assertEqual(evidence.state, ExpenseClaimEvidence.State.ACCEPTED)
            self.assertEqual(recent_evidence.state, ExpenseClaimEvidence.State.ACCEPTED)
            self.assertEqual(
                rejected_evidence.state, ExpenseClaimEvidence.State.REJECTED
            )
            self.assertTrue(path.exists())
            self.assertTrue(recent_path.exists())
            self.assertTrue(rejected_path.exists())
            self.assertIn("DRY RUN: would expire 1", output.getvalue())
            self.assertFalse(
                ExpenseEvidenceAuditEvent.objects.filter(
                    action=ExpenseEvidenceAuditEvent.Action.RETENTION_EXPIRE
                ).exists()
            )

    @override_settings(
        DEBUG=True,
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
    )
    @patch("quotations.evidence_views.ClamAVUnixScanner.scan", return_value=True)
    def test_applied_expiry_tombstones_before_purge_and_records_cutoff(self, _scan):
        with override_settings(EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name):
            evidence, path = self.upload_accepted_evidence()
            evidence.accepted_at = timezone.now() - timedelta(days=3)
            evidence.save(update_fields=["accepted_at"])
            cutoff = (timezone.now() - timedelta(days=2)).replace(microsecond=0)
            call_command(
                "expire_expense_evidence",
                accepted_before=cutoff.isoformat(),
                apply=True,
                reason="Synthetic lifecycle cleanup test",
                verbosity=0,
            )

            evidence.refresh_from_db()
            self.assertEqual(evidence.state, ExpenseClaimEvidence.State.DELETED)
            self.assertIsNotNone(evidence.deleted_at)
            self.assertFalse(path.exists())
            event = ExpenseEvidenceAuditEvent.objects.get(
                evidence=evidence,
                action=ExpenseEvidenceAuditEvent.Action.RETENTION_EXPIRE,
                outcome="expired",
            )
            self.assertEqual(event.outcome, "expired")
            self.assertEqual(
                event.metadata,
                {
                    "accepted_before": cutoff.astimezone(UTC).isoformat(),
                    "reason": "Synthetic lifecycle cleanup test",
                },
            )

    @override_settings(
        DEBUG=True,
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
    )
    @patch("quotations.evidence_views.ClamAVUnixScanner.scan", return_value=True)
    def test_cleanup_reconciles_restored_bytes_without_duplicate_expiry_event(
        self, _scan
    ):
        with override_settings(EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name):
            evidence, path = self.upload_accepted_evidence()
            evidence.accepted_at = timezone.now() - timedelta(days=3)
            evidence.save(update_fields=["accepted_at"])
            cutoff = timezone.now() - timedelta(days=2)
            call_command(
                "expire_expense_evidence",
                accepted_before=cutoff.isoformat(),
                apply=True,
                reason="Synthetic restore cleanup test",
                verbosity=0,
            )
            evidence.refresh_from_db()
            self.assertEqual(evidence.state, ExpenseClaimEvidence.State.DELETED)

            path.write_bytes(b"synthetic restored object bytes")
            call_command("cleanup_expense_evidence", verbosity=0)

            evidence.refresh_from_db()
            self.assertEqual(evidence.state, ExpenseClaimEvidence.State.DELETED)
            self.assertFalse(path.exists())
            self.assertEqual(
                ExpenseEvidenceAuditEvent.objects.filter(
                    evidence=evidence,
                    action=ExpenseEvidenceAuditEvent.Action.RETENTION_EXPIRE,
                    outcome="expired",
                ).count(),
                1,
            )

    @override_settings(
        DEBUG=True,
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
    )
    @patch("quotations.evidence_views.ClamAVUnixScanner.scan", return_value=True)
    @patch(
        "quotations.evidence_deletion.PrivateLocalEvidenceStorage.delete",
        side_effect=OSError("synthetic storage failure"),
    )
    def test_failed_file_purge_keeps_an_inaccessible_retryable_tombstone(
        self, _delete, _scan
    ):
        with override_settings(EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name):
            evidence, path = self.upload_accepted_evidence()
            evidence.accepted_at = timezone.now() - timedelta(days=3)
            evidence.save(update_fields=["accepted_at"])
            cutoff = timezone.now() - timedelta(days=2)

            with self.assertRaisesMessage(
                CommandError, "Some expired evidence remains inaccessible"
            ):
                call_command(
                    "expire_expense_evidence",
                    accepted_before=cutoff.isoformat(),
                    apply=True,
                    reason="Synthetic storage failure test",
                )

            evidence.refresh_from_db()
            self.assertEqual(
                evidence.state, ExpenseClaimEvidence.State.DELETION_PENDING
            )
            self.assertTrue(path.exists())
            self.assertEqual(
                ExpenseEvidenceAuditEvent.objects.filter(
                    evidence=evidence,
                    action=ExpenseEvidenceAuditEvent.Action.RETENTION_EXPIRE,
                ).count(),
                1,
            )

    @override_settings(
        DEBUG=False,
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
    )
    def test_expiry_is_refused_outside_local_synthetic_configuration(self):
        with self.assertRaisesMessage(
            CommandError,
            "Evidence expiry is limited to the gated local synthetic-data configuration.",
        ):
            call_command(
                "expire_expense_evidence",
                accepted_before="2026-10-17T00:00:00+00:00",
                apply=True,
            )

    @override_settings(
        DEBUG=True,
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_STORAGE_ROOT="",
    )
    def test_expiry_requires_aware_cutoff_in_the_past(self):
        with override_settings(EXPENSE_EVIDENCE_STORAGE_ROOT=self.storage.name):
            valid_cutoff = (timezone.now() - timedelta(days=1)).isoformat()
            with self.assertRaisesMessage(CommandError, "--reason is required"):
                call_command(
                    "expire_expense_evidence",
                    accepted_before=valid_cutoff,
                    apply=True,
                )

            for cutoff in (
                "2026-10-17T00:00:00",
                (timezone.now() + timedelta(days=1)).isoformat(),
            ):
                with self.subTest(cutoff=cutoff), self.assertRaises(CommandError):
                    call_command(
                        "expire_expense_evidence",
                        accepted_before=cutoff,
                        apply=True,
                    )
