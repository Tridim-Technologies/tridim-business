# Tridim Business

Tridim Business is a global-ambition business operations platform from Tridim Technologies. The initial workflow and technical foundation are founder-directed; market fit and production readiness remain unvalidated.

## Project status

This repository contains the internal alpha foundation and planning documents. Signed-in organization members can manage customers, prepare quotations, record quotation decisions, and create one linked job when a quotation is accepted. Owners and admins can invite members with one-time, seven-day links; email delivery is not configured. The People area supports an employee directory and basic leave requests with manager decisions; it does not calculate leave balances, entitlements, or payroll. Assigned members can record synthetic expense claims for jobs; reviewers can return, waive missing evidence, approve, or reject them. Receipt uploads and real expense data are not supported. Finance members can issue invoices and record, allocate, and reverse manual receipts. Finance users can also initiate and track sandbox-only Daraja M-Pesa Express attempts from the invoice UI; attempts do not create ledger receipts automatically or enable live payments. Tax and quotation totals are not calculated. The illustrative workflow prototype uses synthetic data, has no backend and saves nothing.

## Start here

1. Read [`docs/PROJECT_CHARTER.md`](docs/PROJECT_CHARTER.md) for product intent and current assumptions.
2. Read [`docs/DETAILED_ROADMAP.md`](docs/DETAILED_ROADMAP.md) for milestone sequence and gates.
3. Review [`docs/VALIDATION_PLAN.md`](docs/VALIDATION_PLAN.md) for build checks and later field-evaluation readiness.
4. Review [`docs/ADR-001-FOUNDATION.md`](docs/ADR-001-FOUNDATION.md) for the accepted initial platform decision.
5. Read [`docs/DARAJA_SANDBOX.md`](docs/DARAJA_SANDBOX.md) before configuring the sandbox M-Pesa Express flow.
6. Review [`docs/DATABASE_BACKUP_AND_RESTORE.md`](docs/DATABASE_BACKUP_AND_RESTORE.md) for the PostgreSQL recovery runbook and local synthetic rehearsal.
7. Open [`prototype/job-to-cash/index.html`](prototype/job-to-cash/index.html) for the sample workflow concept.
8. Read [`docs/EXPENSE_CLAIM_ALPHA.md`](docs/EXPENSE_CLAIM_ALPHA.md) for the synthetic expense claim API and UI.
9. Read [`docs/EMPLOYEE_LEAVE_REQUESTS.md`](docs/EMPLOYEE_LEAVE_REQUESTS.md) for leave request roles, states, privacy boundaries, and API routes.
10. Read [`docs/ORGANIZATION_INVITATIONS.md`](docs/ORGANIZATION_INVITATIONS.md) for invite creation, role limits, signup, and acceptance behavior.

## Scope

This repository is for the Tridim Business core product and its user-facing documentation. The software license has not yet been selected; no license grant should be inferred from this planning repository.

## Current technical direction

The initial stack is Python 3.12+, Django, Django REST Framework, PostgreSQL and TypeScript/React. Python dependencies use uv; frontend dependencies use npm. The product is a modular monolith.

## Run locally

Requirements: `uv`, Python 3.12+, Node.js 22+, and npm. PostgreSQL is recommended; SQLite is available for a quick local start.

```sh
uv sync --locked
uv run python backend/manage.py migrate
uv run python backend/manage.py createsuperuser
uv run python backend/manage.py runserver
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open the Vite URL shown in the terminal. Sign in with the Django superuser only after an organization and membership have been created in Django Admin (`/admin/`). Set `DJANGO_SECRET_KEY`, `DATABASE_URL`, and `DJANGO_DEBUG=0` for non-local environments. Never use local development settings for production.

The expense-evidence upload path is disabled by default. For local synthetic-file development only, set `EXPENSE_EVIDENCE_ENABLED=1` while keeping `DJANGO_DEBUG=1` and `DJANGO_ALLOWED_HOSTS` limited to `localhost,127.0.0.1`; configure `EXPENSE_EVIDENCE_CLAMD_SOCKET` to a local ClamAV Unix socket. Uploads fail closed if the scanner is unavailable. The default private file directory is `.private-evidence/`, which is ignored by Git and is not a production storage adapter. Never use this path with real expense data. See [`docs/EXPENSE_CLAIM_ALPHA.md`](docs/EXPENSE_CLAIM_ALPHA.md) for limits, roles, and cleanup.

## Documentation

Product docs live under `docs/`. Security, privacy, tenant separation, auditability and data portability are core requirements.

Dependency updates use committed lockfiles and reviewable pull requests. See [`docs/DEPENDENCY_MAINTENANCE.md`](docs/DEPENDENCY_MAINTENANCE.md) for the update, security-advisory, and validation process.

## Development checks and releases

Development tooling is managed with [uv](https://docs.astral.sh/uv/) using `pyproject.toml` and the committed `uv.lock` file. Install the locked tools with `uv sync --locked`. Before opening a pull request, run:

```sh
uv run pymarkdown scan README.md 'docs/**/*.md' '.github/**/*.md'
uv run python scripts/check_prototype.py
uv run python backend/manage.py check
uv run python backend/manage.py test accounts customers quotations invoicing
(cd frontend && npm ci && npm run build)
```

Pull requests to `main` run these checks automatically. Merges to `main` run [Python Semantic Release](https://python-semantic-release.readthedocs.io/) and create a version tag and GitHub release for qualifying Conventional Commits. The release command updates the project entry in `uv.lock` with the new version so later locked installs remain in sync. `feat` creates a minor release, `fix` and `perf` create patch releases, and a `!` or `BREAKING CHANGE:` footer creates a major release. Documentation, chores, and CI-only changes do not create a release. No Python package is published.

Use Conventional Commit messages (for example, `feat(workflow): add quote approval`) so release notes and versions can be generated from the project history.
