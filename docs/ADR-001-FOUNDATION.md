# ADR-001: Django Modular Monolith Foundation

**Status:** Accepted for the initial product build; production architecture remains subject to implementation evidence

**Date:** 1 October 2026

**Decision owner:** Founder

## Decision

Build the first Tridim Business application as a **Python + Django + Django REST Framework + PostgreSQL backend with a React + TypeScript web client**. Use a modular monolith with explicit domain boundaries. Manage Python dependencies and environments with `uv`; manage the web client's dependencies with npm and its committed lockfile.

This choice follows the founder's stated direction and available product plan. It is not a claim that customer demand, the target market, or comparative framework fit has been validated. Do not maintain parallel Django and Frappe/ERPNext implementations.

## Product scope for the first build

The starting product hypothesis is growing service businesses that need a connected path from customer and quotation to job, invoice, payment allocation, reconciliation, and owner visibility. Service firms of roughly 10–75 employees are the initial working profile; it is an assumption, not a proven market segment. The product has a global ambition. Kenya is a candidate operating market, not a limit or a compliance claim.

The first software increment establishes sign-in, organization membership, and an organization-scoped customer directory. Subsequent increments should complete the job-to-cash workflow before adding broad ERP, commerce, payroll, inventory, or marketplace scope.

## Architecture guardrails

- Keep the application as a modular monolith. Kubernetes, microservices, a message broker, and multi-region operation are not prerequisites.
- Every business record belongs to an organization; access is checked server-side on every request and operation.
- Use explicit domain operations and status transitions for financial records. Use exact decimal arithmetic, idempotent event processing, auditable corrections, and a single agreed financial source of truth.
- Keep jurisdiction-specific taxes, payroll, payment integrations, and reporting out of scope until their requirements and support responsibilities are verified.
- Use synthetic data during development. Do not load real business records before the pilot-readiness controls are in place.
- Django Admin is a restricted setup and operations tool, not the customer-facing interface.

## Consequences and open decisions

- The stack decision removes a framework comparison as a prerequisite to starting implementation.
- The initial service-business workflow, employee band, beachhead market, accounting boundary, production tenancy model, and detailed role matrix remain assumptions to refine through internal build and later bounded use.
- The software license, production hosting, deployment topology, and support model remain undecided.
- Python 3.12 is the current project baseline for Django 6.0. Reassess dependency support before upgrades.

## References

- [Django 6.0 installation FAQ](https://docs.djangoproject.com/en/6.0/faq/install/)
- [Django REST Framework](https://www.django-rest-framework.org/)
- [React version history](https://react.dev/versions)
- [uv project documentation](https://docs.astral.sh/uv/concepts/projects/)
