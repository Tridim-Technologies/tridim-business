# Tridim Business

Tridim Business is a global-ambition business operations platform from Tridim Technologies. The initial workflow and technical foundation are founder-directed; market fit and production readiness remain unvalidated.

## Project status

This repository contains the internal alpha foundation and planning documents. Signed-in organization members can manage customers, prepare quotations, record quotation decisions, and create one linked job when a quotation is accepted. Finance members can issue invoices and record, allocate, and reverse manual receipts. A sandbox-only Daraja M-Pesa Express attempt and status flow is available for synthetic data; it does not create ledger receipts automatically or enable live payments. Tax and quotation totals are not calculated. The illustrative workflow prototype uses synthetic data, has no backend and saves nothing.

## Start here

1. Read [`docs/PROJECT_CHARTER.md`](docs/PROJECT_CHARTER.md) for product intent and current assumptions.
2. Read [`docs/DETAILED_ROADMAP.md`](docs/DETAILED_ROADMAP.md) for milestone sequence and gates.
3. Review [`docs/VALIDATION_PLAN.md`](docs/VALIDATION_PLAN.md) for build checks and later field-evaluation readiness.
4. Review [`docs/ADR-001-FOUNDATION.md`](docs/ADR-001-FOUNDATION.md) for the accepted initial platform decision.
5. Read [`docs/DARAJA_SANDBOX.md`](docs/DARAJA_SANDBOX.md) before configuring the sandbox M-Pesa Express flow.
6. Review [`docs/DATABASE_BACKUP_AND_RESTORE.md`](docs/DATABASE_BACKUP_AND_RESTORE.md) for the PostgreSQL recovery runbook and local synthetic rehearsal.
7. Open [`prototype/job-to-cash/index.html`](prototype/job-to-cash/index.html) for the sample workflow concept.

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

## Documentation

Product docs live under `docs/`. Security, privacy, tenant separation, auditability and data portability are core requirements.

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
