# Tridim Business

Tridim Business is a proposed global business operations platform from Tridim Technologies. The first customer segment, market and technical foundation remain under validation.

## Project status

This repository currently contains planning documents and an illustrative, static workflow prototype. It does not contain production software. The prototype uses synthetic data, has no backend and saves nothing.

## Start here

1. Read [`docs/PROJECT_CHARTER.md`](docs/PROJECT_CHARTER.md) for product intent and current assumptions.
2. Read [`docs/DETAILED_ROADMAP.md`](docs/DETAILED_ROADMAP.md) for milestone sequence and gates.
3. Review [`docs/ADR-001-FOUNDATION.md`](docs/ADR-001-FOUNDATION.md) for the open platform decision.
4. Open [`prototype/job-to-cash/index.html`](prototype/job-to-cash/index.html) for the sample workflow concept.

## Scope

This repository is for the Tridim Business core product and its user-facing documentation. The software license has not yet been selected; no license grant should be inferred from this planning repository.

## Current technical direction

The leading custom-build hypothesis is Python, Django, Django REST Framework, PostgreSQL and TypeScript/React. Frappe/ERPNext remains an alternative to assess with the same workflow. No production foundation has been selected.

## Documentation

Product docs live under `docs/`. Security, privacy, tenant separation, auditability and data portability are core requirements.

## Development checks and releases

Development tooling is managed with [uv](https://docs.astral.sh/uv/) using `pyproject.toml` and the committed `uv.lock` file. Install the locked tools with `uv sync --locked`. Before opening a pull request, run:

```sh
uv run pymarkdown scan README.md 'docs/**/*.md' '.github/**/*.md'
uv run python scripts/check_prototype.py
```

Pull requests to `main` run these checks automatically. Merges to `main` run [Python Semantic Release](https://python-semantic-release.readthedocs.io/) and create a version tag and GitHub release for qualifying Conventional Commits. `feat` creates a minor release, `fix` and `perf` create patch releases, and a `!` or `BREAKING CHANGE:` footer creates a major release. Documentation, chores, and CI-only changes do not create a release. No Python package is published.

Use Conventional Commit messages (for example, `feat(workflow): add quote approval`) so release notes and versions can be generated from the project history.
