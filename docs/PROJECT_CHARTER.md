# Tridim Business Platform — Project Charter

**Status:** Build charter; market assumptions and production readiness remain unvalidated

**Last updated:** 1 October 2026

**Parent company:** Tridim Technologies

**Product name:** Tridim Business Platform

**Short name:** Tridim Business

## Purpose and vision

Tridim Business aims to help growing businesses run connected day-to-day operations in one place, with a global market ambition. The long-term product may include sales and CRM, jobs and projects, finance, people operations, inventory and merchant commerce.

The starting workflow is customer → quotation → accepted job → staff assignment → time and expenses → invoice → payment allocation → reconciliation → owner reporting. Build a narrow, dependable workflow before adding broad modules. Kenya is a candidate market, not the product boundary. Global-ready data design does not establish legal, tax, payroll, payment or privacy compliance in any country.

The initial segment hypothesis is service businesses with approximately 10–75 employees, including technical support, installation, maintenance, consultancy and agency firms. This is a working product assumption, not validated demand. The product name is a preference, not trademark clearance. Do not use Tandivaro or Kelvumo in new branding, repositories, package identifiers or public materials.

## Product boundary

The first build establishes sign-in, organization membership and an organization-scoped customer directory. Continue with quotations and accepted jobs, then delivery, invoices, payments and reconciliation. Roles begin with owner/admin, sales, operations, finance and employee profiles; refine them alongside implemented workflows.

Keep organization separation, server-side authorization, auditability, privacy and data portability as core requirements. Use synthetic data during development. Do not use real business data until evaluation safeguards are reviewed. The first increment does not claim accounting-system completeness, country compliance or production readiness.

### Initial exclusions

- Payroll calculations and statutory filings.
- Multi-vendor marketplace, pooled customer funds, split settlements or Tridim wallet.
- Manufacturing, advanced inventory, POS, recruitment, appraisals, advanced attendance, assets, budgeting and advanced analytics.
- Native Android/iOS apps before a concrete device or offline requirement exists.
- Country compliance, certifications, service levels or savings claims that have not been verified.

Merchant-branded storefronts remain a possible longer-term direction. Keep storefront identity distinct from the internal business administration experience.

## Technical foundation

The founder-selected starting stack is Python, Django, Django REST Framework, PostgreSQL and React/TypeScript. Use a modular monolith, `uv` for Python dependency management, and npm with a committed lockfile for the frontend. FastAPI is not part of the selected direction. Do not maintain a parallel Frappe/ERPNext implementation.

Kubernetes, microservices, a message broker and multi-region operation are not MVP prerequisites. Every business record belongs to an organization and access is enforced server-side. Use explicit operations for financial state changes, exact monetary arithmetic, idempotent event handling, auditable corrections and one agreed financial source of truth. Add background workers and object storage when actual workflow needs justify them.

## Build and validation approach

Proceed using the available product requirements and stated founder direction. Keep assumptions visible in the docs and issues; distinguish implementation evidence from evidence of market demand. Validate internally with synthetic scenarios, authorization tests, financial invariants, export, backup and recovery checks. Field evaluation with real data remains a later gate requiring privacy, security, support and recovery readiness.

## Core principles

- Deliver one coherent job-to-cash workflow before expanding module count.
- Keep enterprise-only product direction and documentation in the separate enterprise repository.
- Prefer reusable documented interfaces and avoid duplicated core business logic.
- Do not claim product-market fit, country compliance, certification or production readiness without evidence.
- The software license, production hosting, deployment topology and support model remain undecided.

## Roadmap and risks

Milestones, dependencies, and exit criteria are maintained in [`DETAILED_ROADMAP.md`](DETAILED_ROADMAP.md), with the immediate implementation sequence in [`ROADMAP_BACKLOG.md`](ROADMAP_BACKLOG.md). Dates remain uncommitted until team capacity is known.

Key risks include tenant data exposure, financial-state errors, jurisdiction-specific changes, scope expansion, unverified market demand, and unresolved brand/license decisions. Address the first two through server-side isolation, automated tests, exact arithmetic and auditable state transitions. Defer real-data evaluation until operational controls and qualified review are complete.
