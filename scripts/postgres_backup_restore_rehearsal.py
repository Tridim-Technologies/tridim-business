"""Run a backup/restore rehearsal on a disposable local PostgreSQL cluster."""

import getpass
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
BACKUP_FIXTURE = r"""
from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from accounts.models import Membership, Organization
from customers.models import Customer
from invoicing.models import Invoice, InvoiceLine, Payment, PaymentAllocation
from quotations.models import Job, Quotation, QuotationLine

user = get_user_model().objects.create_user(
    username="backup-rehearsal-user", password=None
)
organization = Organization.objects.create(name="Backup Restore Rehearsal")
Membership.objects.create(
    organization=organization, user=user, role=Membership.Role.OWNER
)
customer = Customer.objects.create(
    organization=organization,
    name="Synthetic Recovery Customer",
    created_by=user,
)
today = date.today()
quotation = Quotation.objects.create(
    organization=organization,
    customer=customer,
    currency="KES",
    valid_until=today + timedelta(days=14),
    status=Quotation.Status.ACCEPTED,
    created_by=user,
)
QuotationLine.objects.create(
    quotation=quotation,
    description="Synthetic recovery service",
    quantity=Decimal("1.000"),
    unit_price=Decimal("100.00"),
)
job = Job.objects.create(
    organization=organization,
    customer=customer,
    source_quotation=quotation,
    status=Job.Status.COMPLETED,
    created_by=user,
)
invoice = Invoice.objects.create(
    organization=organization,
    job=job,
    source_quotation=quotation,
    customer=customer,
    customer_name=customer.name,
    invoice_number="RECOVERY-REHEARSAL-001",
    status=Invoice.Status.ISSUED,
    issue_date=today,
    due_date=today + timedelta(days=30),
    currency="KES",
    total=Decimal("100.00000"),
    issued_by=user,
)
InvoiceLine.objects.create(
    invoice=invoice,
    description="Synthetic recovery service",
    quantity=Decimal("1.000"),
    unit_price=Decimal("100.00"),
    line_total=Decimal("100.00000"),
)
payment = Payment.objects.create(
    organization=organization,
    customer=customer,
    customer_name=customer.name,
    received_date=today,
    amount=Decimal("100.00000"),
    currency="KES",
    method=Payment.Method.BANK_TRANSFER,
    reference="RECOVERY-REHEARSAL-PAYMENT",
    recorded_by=user,
)
PaymentAllocation.objects.create(
    payment=payment,
    invoice=invoice,
    amount=Decimal("100.00000"),
    allocated_by=user,
)
print("synthetic_fixture_created")
"""

VERIFY_FIXTURE = r"""
from decimal import Decimal
from accounts.models import Organization
from customers.models import Customer
from invoicing.models import Invoice, Payment, PaymentAllocation

organization = Organization.objects.get(name="Backup Restore Rehearsal")
customer = Customer.objects.get(
    organization=organization, name="Synthetic Recovery Customer"
)
invoice = Invoice.objects.get(
    organization=organization, invoice_number="RECOVERY-REHEARSAL-001"
)
payment = Payment.objects.get(
    organization=organization, reference="RECOVERY-REHEARSAL-PAYMENT"
)
allocation = PaymentAllocation.objects.get(payment=payment, invoice=invoice)
assert invoice.customer_id == customer.pk
assert payment.customer_id == customer.pk
assert invoice.total == Decimal("100.00000")
assert payment.amount == Decimal("100.00000")
assert allocation.amount == Decimal("100.00000")
assert Invoice.objects.filter(organization=organization).count() == 1
assert Payment.objects.filter(organization=organization).count() == 1
print("verified organization, customer, invoice, payment, and allocation relationships")
"""


def run(step, args, *, env=None, capture=False):
    try:
        return subprocess.run(
            args,
            cwd=ROOT,
            env=env,
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except subprocess.CalledProcessError as error:
        details = (error.stderr or error.stdout or "").strip()
        details = details.replace(str(ROOT), "<project>")
        details = re.sub(
            r"/tmp/tridim-postgres-rehearsal-[^/\s]+", "<temporary>", details
        )
        raise RuntimeError(
            f"Rehearsal step failed: {step}. {details or 'Details unavailable.'}"
        ) from error


def postgres_bin_directory():
    postgres = shutil.which("postgres")
    if not postgres:
        raise RuntimeError("PostgreSQL server tools are required (postgres not found).")
    directory = Path(postgres).resolve().parent
    required = ("initdb", "pg_ctl", "createdb", "pg_dump", "pg_restore")
    missing = [name for name in required if not (directory / name).is_file()]
    if missing:
        raise RuntimeError(
            f"Missing PostgreSQL tools beside postgres: {', '.join(missing)}"
        )
    return directory


def available_local_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def database_url(username, password, database, port):
    return (
        f"postgresql://{quote(username, safe='')}:{quote(password, safe='')}"
        f"@127.0.0.1:{port}/{database}"
    )


def django_env(base, username, password, database, port):
    env = base.copy()
    env.update(
        {
            "DATABASE_URL": database_url(username, password, database, port),
            "DJANGO_DEBUG": "1",
            "DJANGO_SECRET_KEY": secrets.token_urlsafe(48),
            "DARAJA_ENV": "sandbox",
            "DARAJA_CONSUMER_KEY": "",
            "DARAJA_CONSUMER_SECRET": "",
            "DARAJA_SHORTCODE": "",
            "DARAJA_PASSKEY": "",
            "DARAJA_CALLBACK_URL": "",
        }
    )
    return env


def main():
    if getpass.getuser() == "root":
        raise RuntimeError("Do not run this rehearsal as root; initdb rejects root.")

    bin_dir = postgres_bin_directory()
    port = available_local_port()
    username = "tridim_rehearsal"
    password = secrets.token_urlsafe(24)
    env = {
        key: os.environ[key]
        for key in (
            "PATH",
            "TMPDIR",
            "TEMP",
            "SYSTEMROOT",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
        )
        if key in os.environ
    }
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["PGSSLMODE"] = "disable"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="tridim-postgres-rehearsal-") as temp_name:
        temp = Path(temp_name)
        data_dir = temp / "cluster"
        log_path = temp / "postgres.log"
        backup_path = temp / "database.dump"
        pgpass = temp / "pgpass"
        pwfile = temp / "initdb-password"
        pgpass.write_text(f"127.0.0.1:{port}:*:{username}:{password}\n")
        pgpass.chmod(0o600)
        pwfile.write_text(f"{password}\n")
        pwfile.chmod(0o600)
        env["PGPASSFILE"] = str(pgpass)

        server_started = False
        try:
            run(
                "initialize temporary PostgreSQL cluster",
                [
                    str(bin_dir / "initdb"),
                    "-D",
                    str(data_dir),
                    "--username",
                    username,
                    "--pwfile",
                    str(pwfile),
                    "--auth-local=scram-sha-256",
                    "--auth-host=scram-sha-256",
                ],
                env=env,
                capture=True,
            )
            pwfile.unlink()
            run(
                "start local-only PostgreSQL cluster",
                [
                    str(bin_dir / "pg_ctl"),
                    "-D",
                    str(data_dir),
                    "--log",
                    str(log_path),
                    "--options",
                    f"-h 127.0.0.1 -p {port} -c listen_addresses=127.0.0.1 -c unix_socket_directories=''",
                    "--wait",
                    "start",
                ],
                env=env,
                capture=True,
            )
            server_started = True
            source = "tridim_backup_source"
            restored = "tridim_backup_restored"
            for database in (source, restored):
                run(
                    f"create isolated database {database}",
                    [
                        str(bin_dir / "createdb"),
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--username",
                        username,
                        database,
                    ],
                    env=env,
                    capture=True,
                )

            source_env = django_env(env, username, password, source, port)
            manage = [sys.executable, str(ROOT / "backend" / "manage.py")]
            run(
                "apply project migrations",
                manage + ["migrate", "--noinput"],
                env=source_env,
                capture=True,
            )
            run(
                "create synthetic recovery fixture",
                manage + ["shell", "-c", BACKUP_FIXTURE],
                env=source_env,
                capture=True,
            )

            run(
                "create custom-format PostgreSQL dump",
                [
                    str(bin_dir / "pg_dump"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--username",
                    username,
                    "--format=custom",
                    "--file",
                    str(backup_path),
                    source,
                ],
                env=env,
                capture=True,
            )
            run(
                "restore dump to separate empty database",
                [
                    str(bin_dir / "pg_restore"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--username",
                    username,
                    "--exit-on-error",
                    "--single-transaction",
                    "--no-owner",
                    "--no-privileges",
                    "--dbname",
                    restored,
                    str(backup_path),
                ],
                env=env,
                capture=True,
            )

            restored_env = django_env(env, username, password, restored, port)
            run(
                "check restored Django database",
                manage + ["check"],
                env=restored_env,
                capture=True,
            )
            run(
                "check restored migration state",
                manage + ["migrate", "--check"],
                env=restored_env,
                capture=True,
            )
            verification = run(
                "verify restored synthetic records",
                manage + ["shell", "-c", VERIFY_FIXTURE],
                env=restored_env,
                capture=True,
            )
            print(verification.stdout.strip())
            print(f"backup_archive_bytes={backup_path.stat().st_size}")
            print(
                "PostgreSQL backup/restore rehearsal passed; temporary data will be removed."
            )
        finally:
            if server_started:
                run(
                    "stop temporary PostgreSQL cluster",
                    [
                        str(bin_dir / "pg_ctl"),
                        "-D",
                        str(data_dir),
                        "--wait",
                        "--mode=fast",
                        "stop",
                    ],
                    env=env,
                    capture=True,
                )


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError) as error:
        raise SystemExit(str(error)) from error
