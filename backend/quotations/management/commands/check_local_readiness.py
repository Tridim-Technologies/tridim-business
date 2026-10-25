from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from quotations.evidence import ClamAVUnixScanner, EvidenceScannerUnavailable


class Command(BaseCommand):
    help = (
        "Check the local synthetic-data readiness gates without changing business data."
    )

    def handle(self, *args, **options):
        failures = []
        checks = []

        checks.append(("development mode", settings.DEBUG))
        checks.append(
            ("local host allowlist", settings.EXPENSE_EVIDENCE_LOCAL_HOSTS_ALLOWED)
        )
        checks.append(
            ("abuse cleanup command", "cleanup_abuse_records" in self._commands())
        )
        checks.append(
            ("evidence cleanup command", "cleanup_expense_evidence" in self._commands())
        )
        checks.append(
            (
                "evidence quarantine window",
                settings.EXPENSE_EVIDENCE_QUARANTINE_SECONDS > 0,
            )
        )
        checks.append(
            ("evidence file limit", settings.EXPENSE_EVIDENCE_MAX_FILE_BYTES > 0)
        )
        checks.append(
            (
                "evidence claim file limit",
                settings.EXPENSE_EVIDENCE_MAX_FILES_PER_VERSION > 0,
            )
        )
        checks.append(
            ("evidence total limit", settings.EXPENSE_EVIDENCE_MAX_TOTAL_BYTES > 0)
        )

        if settings.EXPENSE_EVIDENCE_ENABLED:
            storage = Path(settings.EXPENSE_EVIDENCE_STORAGE_ROOT).expanduser()
            ledger = Path(settings.EXPENSE_EVIDENCE_LEDGER_ROOT).expanduser()
            checks.extend(
                [
                    ("private evidence path", self._private_path(storage)),
                    ("private deletion journal path", self._private_path(ledger)),
                ]
            )
            try:
                ClamAVUnixScanner().scan(b"")
                checks.append(("ClamAV Unix socket", True))
            except EvidenceScannerUnavailable:
                checks.append(("ClamAV Unix socket", False))
        else:
            self.stdout.write(
                "Expense evidence gate: disabled (synthetic upload is not enabled)."
            )

        for label, passed in checks:
            if passed:
                self.stdout.write(self.style.SUCCESS(f"PASS: {label}"))
            else:
                failures.append(label)
                self.stdout.write(self.style.ERROR(f"FAIL: {label}"))

        if failures:
            raise CommandError(
                "Local readiness failed: " + ", ".join(failures) + ". "
                "This command never authorizes real data or production use."
            )
        self.stdout.write(
            self.style.SUCCESS(
                "Local readiness checks passed. This result applies only to synthetic development."
            )
        )

    @staticmethod
    def _private_path(path):
        return path.is_absolute() and not path.is_symlink()

    @staticmethod
    def _commands():
        from django.core.management import get_commands

        return get_commands()
