# M5 local synthetic operating checklist

This checklist is the repeatable operating path for the current internal-alpha
development baseline. Use synthetic organizations, customers, invoices, jobs,
claims, and generated evidence only.

## Before starting

- Confirm the checkout is on the current `main` branch and dependencies are
  installed from the lockfile with `uv sync --locked`.
- Use a disposable local PostgreSQL database and private temporary directories.
- Keep `DJANGO_DEBUG=1`, `DJANGO_ALLOWED_HOSTS` limited to local hosts, and
  `EXPENSE_EVIDENCE_ENABLED=0` unless deliberately exercising the synthetic
  evidence path.
- Never place credentials, real receipts, customer data, or production URLs in
  this workflow.

## Readiness gate

Run from the repository root:

```sh
uv run python backend/manage.py check
uv run python backend/manage.py check_local_readiness
```

The readiness command verifies development mode, local host policy, bounded
evidence settings, cleanup command discovery, private evidence paths, and the
ClamAV Unix socket when synthetic evidence is enabled. A successful result is a
diagnostic for local synthetic development only; it never authorizes real data,
production use, or hosted deployment. A failed result is a stop condition.

## During a local rehearsal

- Keep the application, database, and scanner logs local and free of secrets.
- Run `cleanup_abuse_records` at least every five minutes when exercising login
  or public callback behavior:

  ```sh
  uv run python backend/manage.py cleanup_abuse_records
  ```

- Run evidence cleanup after synthetic evidence tests:

  ```sh
  uv run python backend/manage.py cleanup_expense_evidence
  ```

- Use the backup/restore runbook only with disposable synthetic data. The local
  rehearsal does not prove hosted point-in-time recovery or object-storage
  deletion guarantees.

## Stop and record

Stop the rehearsal if a readiness check fails, a scanner or private path is
unavailable, or any non-synthetic data enters the workflow. Remove only the
temporary database and evidence directories created for the rehearsal. Record
the command results and unresolved limitations in the relevant issue; do not
interpret a green local check as a field-evaluation approval.

## Explicitly outside this checklist

Hosted deployment, alert routing, scheduled jobs in a hosted environment,
production evidence storage or retention, independent recovery checkpoints,
real business data, live payments, and the uncancelled Daraja sandbox handset
follow-up remain separate deferred work.
