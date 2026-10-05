# Product Build Backlog

**Status:** Founder-directed starting scope; market fit and production readiness are not validated

**Last updated:** 5 October 2026

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

**Implementation progress:** The workflow supports tenant-scoped quote drafts, line items, validity dates, send/accept/reject/withdraw transitions, status history, and one linked job per accepted quote. Issue #9 adds auditable customer archive/restore and search, plus immutable quote revisions with their own line items and status history. The milestone remains open until the slice is merged and the remaining job delivery fields are defined.

## P2 — Delivery to receivable visibility

- Add job status, assignments, due dates, and delivery notes.
- Add invoices from completed/accepted work and define a controlled correction path.
- Provide owner/finance views for open work and outstanding invoices.
- **Acceptance:** synthetic scenarios produce explainable job and receivable states; the app does not imply full accounting.

## P3 — Payments and reconciliation

- Begin with explicit manual payment recording and allocation.
- Add idempotent provider events only after a provider route, onboarding needs, and failure recovery are understood.
- Cover partial, unmatched, duplicated, delayed, reversed, refunded, and overpaid cases.
- **Acceptance:** balances use exact arithmetic; event retries do not duplicate records; unresolved exceptions are visible and recoverable.

## P4 — Evaluation readiness

- Complete organization/role security review, export, backup/restore, monitoring, and recovery documentation.
- Define a bounded field evaluation, responsibilities, privacy safeguards, rollback, baseline, and support process.
- **Acceptance:** qualified reviewers accept the safeguards and a restore rehearsal succeeds before real business data is used.

## Later candidates, not committed scope

Merchant-owned storefronts, inventory, POS, purchasing, recurring billing, advanced HR/attendance, recruitment, payroll, native apps, analytics, marketplace, and multi-country tax/payroll remain future candidates. Reprioritize them only when implementation learning, available information, specialist review, and delivery capacity justify the work.
