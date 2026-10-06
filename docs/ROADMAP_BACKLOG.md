# Product Build Backlog

**Status:** Founder-directed starting scope; market fit and production readiness are not validated

**Last updated:** 6 October 2026

This backlog turns the existing product plan into an implementation sequence. It does not represent customer commitments or a delivery date.

## P0 — Application foundation

- Set up the Django/DRF and React/TypeScript modular monolith with reproducible Python and frontend dependencies.
- Add organization and membership records, authenticated workspace selection, and a customer directory scoped to organization membership.
- Add API authorization tests, local PostgreSQL support, migrations, and a synthetic-data development guide.
- **Acceptance:** a developer can run the app locally; a signed-in user can manage customers only in an authorized organization; cross-organization access is denied.

## P1 — Customer to accepted job

- Add customer contact details and lifecycle management.
- Add quotations, line items, revisions, expiry, and explicit acceptance/rejection transitions.
- Create a linked job idempotently when an authorized user accepts a quotation.
- **Acceptance:** the customer → quote → accepted job path works with audit history and tenant-scoped authorization.

**Implementation progress:** P1 is complete in v0.3.0: customers have auditable active/archived lifecycle and search, quotations have immutable revisions and status history, and accepting the current valid revision creates one tenant-scoped job. Job delivery status, assignments, due dates, and notes shipped in v0.4.0.

## P2 — Delivery to receivable visibility

- Add job status, assignments, due dates, and delivery notes.
- Add invoices from completed/accepted work and define a controlled correction path.
- Provide owner/finance views for open jobs and issued invoice totals with due dates. Show an outstanding balance only after payment allocations are tracked.
- **Acceptance:** synthetic scenarios produce explainable job and issued-invoice states; any balance is based on recorded allocations, and the app does not imply full accounting.

**Implementation progress:** P2 is complete in v0.5.0. Issue #11 shipped auditable job status, assignments, due dates, and delivery notes; issue #13 shipped the internal invoice register with per-organization annual numbering, void-and-reissue history, and owner/finance invoice visibility. Tax, payment allocation, and jurisdictional compliance are outside P2.

## P3 — Payments and reconciliation

- Begin with explicit manual payment recording and allocation.
- Add idempotent provider events only after a provider route, onboarding needs, and failure recovery are understood.
- Cover partial, unmatched, duplicated, delayed, reversed, refunded, and overpaid cases.
- **Acceptance:** balances use exact arithmetic; event retries do not duplicate records; unresolved exceptions are visible and recoverable.

**Implementation progress:** Issue #15 shipped manual receipts, same-customer/same-currency invoice allocations, derived balances, and auditable reversal paths in v0.6.0. Issue #19 shipped tenant-scoped finance CSV exports that preserve unmatched and reversed states in v0.7.0. Issue #23 established the provider-neutral event boundary, and issue #25 documented tenant credential safeguards. Issue #29 selects Safaricom Daraja M-Pesa Express/STK Push as the provisional first sandbox connector for Kenya-focused tenant invoice collections; Flutterwave is deferred for later evaluation. No connector or live payments are shipped. ADR-004 recommends Cloud Run + Cloud SQL for PostgreSQL + Secret Manager as the initial hosted reference path; Kubernetes is optional, and region/sizing still require readiness and cost review. Live tenant shortcode connections remain blocked until Safaricom confirms the SaaS model and merchant onboarding in writing. Continue manual payment recording meanwhile; the next technical slice is a sandbox-only Daraja attempt/callback/status-verification flow using synthetic data.

## P4 — Evaluation readiness

Before real business data is introduced, choose the actual region and database sizing, document support ownership and recovery objectives, configure monitoring and backup retention, complete a database restore rehearsal and secret rotation/access review, and obtain Safaricom's written approval of the tenant account model before enabling live Daraja connections. Kubernetes is not a prerequisite.

- Complete organization/role security review, export, backup/restore, monitoring, and recovery documentation.
- Define a bounded field evaluation, responsibilities, privacy safeguards, rollback, baseline, and support process.
- **Acceptance:** qualified reviewers accept the safeguards and a restore rehearsal succeeds before real business data is used.

## Later candidates, not committed scope

Merchant-owned storefronts, inventory, POS, purchasing, recurring billing, advanced HR/attendance, recruitment, payroll, native apps, analytics, marketplace, and multi-country tax/payroll remain future candidates. Reprioritize them only when implementation learning, available information, specialist review, and delivery capacity justify the work.
