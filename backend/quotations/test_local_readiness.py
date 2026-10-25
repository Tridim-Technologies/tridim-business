from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.core import management
from django.test import SimpleTestCase, override_settings


class LocalReadinessCommandTests(SimpleTestCase):
    @override_settings(
        DEBUG=True,
        ALLOWED_HOSTS=["localhost", "127.0.0.1"],
        EXPENSE_EVIDENCE_ENABLED=False,
    )
    def test_disabled_evidence_gate_reports_safe_synthetic_baseline(self):
        management.call_command("check_local_readiness")

    @override_settings(
        DEBUG=False,
        EXPENSE_EVIDENCE_ENABLED=True,
    )
    def test_production_mode_fails_closed(self):
        with self.assertRaises(management.base.CommandError):
            management.call_command("check_local_readiness")

    @override_settings(
        DEBUG=True,
        ALLOWED_HOSTS=["localhost", "127.0.0.1"],
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_CLAMD_SOCKET="/private/tmp/missing-clamd.sock",
    )
    def test_enabled_evidence_gate_requires_scanner(self):
        with TemporaryDirectory() as root:
            with override_settings(
                EXPENSE_EVIDENCE_STORAGE_ROOT=Path(root) / "evidence",
                EXPENSE_EVIDENCE_LEDGER_ROOT=Path(root) / "ledger",
            ):
                with self.assertRaises(management.base.CommandError):
                    management.call_command("check_local_readiness")

    @override_settings(
        DEBUG=True,
        ALLOWED_HOSTS=["localhost", "127.0.0.1"],
        EXPENSE_EVIDENCE_ENABLED=True,
        EXPENSE_EVIDENCE_CLAMD_SOCKET="/private/tmp/test-clamd.sock",
    )
    def test_enabled_evidence_gate_passes_with_clean_scanner(self):
        with TemporaryDirectory() as root:
            with override_settings(
                EXPENSE_EVIDENCE_STORAGE_ROOT=Path(root) / "evidence",
                EXPENSE_EVIDENCE_LEDGER_ROOT=Path(root) / "ledger",
            ):
                with patch(
                    "quotations.management.commands.check_local_readiness.ClamAVUnixScanner.scan",
                    return_value=True,
                ):
                    management.call_command("check_local_readiness")
