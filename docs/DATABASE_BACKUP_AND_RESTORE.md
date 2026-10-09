# PostgreSQL backup and restore runbook

**Status:** Local synthetic-data rehearsal verified; hosted recovery settings and service targets remain undecided.

This runbook describes how to protect and recover the Tridim Business Platform PostgreSQL database. The project recommends Cloud SQL for PostgreSQL for an initial hosted deployment, but has not selected a project, region, database size, recovery objectives, retention period, or operating owner. This document does not claim production readiness or establish an RPO/RTO.

## Recovery decisions required before real data

Record and approve these values for each deployed environment before it stores real business records:

| Decision | Current state |
| --- | --- |
| Database/project and region | Not selected; see [ADR-004](ADR-004-HOSTING-AND-PAYMENT-ACCOUNTS.md) |
| Recovery point objective (RPO) | Not set; choose based on acceptable data loss and provider configuration |
| Recovery time objective (RTO) | Not set; rehearse against the selected deployment and measured data volume |
| Backup/PITR retention | Not set; choose to satisfy recovery, legal, and cost requirements |
| Backup and restore operator | Not assigned |
| Alert owner and escalation path | Not assigned |
| Backup encryption and key/access policy | Must be confirmed for the chosen storage and deployment |

Do not substitute vendor defaults for an explicit product recovery target. Revisit these decisions if the data location, database edition, or deployment design changes.

## Backup requirements

- Use the hosting provider's managed automated backups and point-in-time recovery (PITR) where supported. Configure and monitor them explicitly; a managed database does not mean the recovery policy has been selected.
- Keep an additional logical backup when portability or an independent recovery path is required. PostgreSQL's custom `pg_dump` archive can be restored selectively with `pg_restore` and is compressed by default; use compatible PostgreSQL client tools and review any dump warnings. See the [PostgreSQL `pg_dump` documentation](https://www.postgresql.org/docs/16/app-pgdump.html).
- Write artifacts only to an approved encrypted storage location with least-privilege read/write access, retention/deletion controls, and auditability. A `pg_dump` archive is not itself an encryption boundary.
- Protect database credentials outside command arguments and logs. Use the deployment's identity/secret mechanism or a permissions-restricted password file such as `PGPASSFILE` (mode `0600`) for operator-run PostgreSQL tools. Do not place passwords in command-line URLs, shell history, repository files, issue comments, or terminal output.
- Keep backup creation and restore roles separate from ordinary application credentials where the hosting model allows it. Restrict who can delete backups and who can restore them.
- Track backup success, age, size, retention, and storage capacity. Alert an assigned operator on a missed backup, failed PITR/log archival, unexpected growth, or retention failure.

For a self-managed PostgreSQL environment, an operator can create a custom archive using protected connection configuration, for example:

```sh
umask 077
export PGPASSFILE=/secure/operator-managed/path/pgpass
pg_dump \
  --host="$PGHOST" \
  --port="$PGPORT" \
  --username="$PGUSER" \
  --dbname="$PGDATABASE" \
  --format=custom \
  --file="$BACKUP_FILE"
```

Provision the password file through the approved secret process; do not paste an actual password into this example. Store the result in the approved encrypted destination and verify that `pg_restore --list "$BACKUP_FILE"` can read its table of contents. Avoid copying production archives to a developer laptop unless the data owner has explicitly approved that handling.

## Restore procedure

1. Declare the incident, assign the recovery operator, stop or control writes as the incident plan requires, and record the suspected recovery point.
2. Select a known-good managed backup/PITR point or verified logical archive. Preserve the source instance and backup evidence.
3. Restore into a **new, isolated target** first. Do not use `pg_restore --clean` or restore over the only source copy as the normal rehearsal/recovery path. Cloud SQL PITR creates a new instance; a normal backup restore to an existing instance can overwrite its data. Review the current [Cloud SQL restore overview](https://docs.cloud.google.com/sql/docs/postgres/backup-recovery/restore) and [PITR procedure](https://docs.cloud.google.com/sql/docs/postgres/backup-recovery/pitr) before deployment because provider options can change.
4. For a logical archive, create an empty target database, inspect the archive, and restore with errors stopping the operation. For example, with target connection values supplied through protected `PG*` settings and `PGPASSFILE`:

   ```sh
   pg_restore \
     --host="$RESTORE_PGHOST" \
     --port="$RESTORE_PGPORT" \
     --username="$RESTORE_PGUSER" \
     --dbname="$RESTORE_PGDATABASE" \
     --exit-on-error \
     --single-transaction \
     --no-owner \
     --no-privileges \
     "$BACKUP_FILE"
   ```

   The target database must be empty and separate from the source. Restore credentials must be supplied through the approved protected mechanism, not as a password argument.

   A per-database `pg_dump` does not provision cluster roles or secrets. Provision target roles and runtime grants through the approved infrastructure/identity process before cutover; when restoring with `--no-owner --no-privileges`, the restore role owns the restored objects and grants must be reapplied. Verify the app's actual database identity can read and write the required tables. If role/global-object export is required in a self-managed environment, treat that file as highly sensitive because it can contain credential material; do not restore it without review.

5. Run Django system and migration checks against the restored database. Verify representative organizations, memberships, customers, quotations/jobs, invoices, payments, allocations, and relevant audit/history records; reconcile record counts and totals against an agreed baseline.
6. Verify the recovered app can connect using the intended identity and secret configuration. Keep the recovered instance isolated until the data owner approves cutover. A cutover plan must cover write freeze, endpoint/configuration change, smoke checks, rollback, and how writes made after the recovery point are reconciled.
7. Record the selected backup/recovery point, elapsed times, validation results, data gaps, and follow-up actions. Delete temporary copies and instances through the approved retention process after the owner authorizes cleanup.

Cloud SQL automated backups and PITR configuration are deployment work, not created by this repository. The [Cloud SQL backup overview](https://docs.cloud.google.com/sql/docs/postgres/backup-recovery/backups) and [PITR configuration guide](https://docs.cloud.google.com/sql/docs/postgres/backup-recovery/configure-pitr) describe the provider controls. Select a retention window and log-storage setting only after the recovery targets, region, cost, and residency requirements are agreed.

## Local synthetic rehearsal

Run the repeatable local rehearsal with the project virtual environment and PostgreSQL server tools (`postgres`, `initdb`, `pg_ctl`, `createdb`, `pg_dump`, and `pg_restore`) on `PATH`:

```sh
uv run python scripts/postgres_backup_restore_rehearsal.py
```

The script creates a temporary PostgreSQL cluster bound to `127.0.0.1` on a selected unused port, with an ephemeral database user/password, a restrictive temporary directory, and no Daraja credentials. It migrates a **disposable** source database, creates a synthetic organization/customer/quotation/job/invoice/payment/allocation, writes a custom-format archive, restores into a different empty database, and checks Django system/migration state and the recovered relationships/totals. It then stops PostgreSQL and deletes the temporary cluster and archive. It never reads the repository `.env` or existing `db.sqlite3`.

### Rehearsal evidence

On 9 October 2026, the script passed locally with PostgreSQL 16. It verified one synthetic organization, customer, invoice, payment, and allocation after restoring the archive; Django system checks and migration-state checks passed. The temporary database cluster and dump were removed by the script. This verifies the project schema and a logical dump/restore workflow on one local PostgreSQL installation only. It does not test Cloud SQL backups/PITR, encrypted remote storage, monitoring/alerting, production data volume, or a deployment cutover.

## Operational ownership and status

The recovery operator, alert recipient, RPO, RTO, retention, region, and hosted backup policy remain unassigned or unset. Assign them before any real-data evaluation. Rehearse a restore after material schema/deployment changes and at the cadence selected by the responsible operator; a backup is not considered verified until restore evidence exists.
