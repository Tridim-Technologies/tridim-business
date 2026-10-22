# Product Build Backlog

**Status:** Founder-directed starting scope; market fit and production readiness are not validated

**Last updated:** 22 October 2026

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

**Implementation progress:** P2 delivered job delivery and invoicing in v0.5.0. Issue #11 shipped auditable job status, assignments, due dates, and delivery notes; issue #13 shipped the internal invoice register with per-organization annual numbering, void-and-reissue history, and owner/finance invoice visibility. Issue #47 adds assigned-staff time entry and manager approval. Issue #49 defines the private evidence lifecycle in [ADR-005](ADR-005-EXPENSE-EVIDENCE-HANDLING.md); issue #51 defines the [expense claim MVP workflow](EXPENSE_CLAIM_MVP_WORKFLOW.md); issue #53 implements the [synthetic claim core](EXPENSE_CLAIM_ALPHA.md). Issue #61 adds a gated local synthetic evidence path; real-data use remains blocked on production controls and operating decisions in ADR-005. Tax, payment allocation, and jurisdictional compliance are outside P2.

**Core HR increment:** Issue #59 adds the first work-only employee directory linked to organization memberships. Issue #87 adds tenant-scoped leave requests and auditable manager decisions. Issue #89 adds organization invitations and account onboarding with constrained roles and single-use links. Issue #91 adds optional SMTP-backed invitation email with a manual-link fallback; mailbox verification remains outside this increment. Leave balances, entitlements, payroll, statutory policy, and sensitive identity records remain outside this increment.

**Inventory increment:** Issue #105 adds an organization-scoped product catalog, stock locations, and append-only receipt, issue, adjustment, and transfer movements with decimal quantities, reason/actor history, negative-stock protection, and idempotent request keys. Quantities are derived from the movement history. Purchasing, reservations, costing, valuation, tax, and accounting are outside this increment; see [Synthetic Inventory Alpha](INVENTORY_ALPHA.md).

**Supplier purchasing increment:** Issue #107 adds tenant-scoped suppliers, draft/issued/cancelled supplier orders, and idempotent partial/full receiving linked atomically to inventory movements. Order history snapshots supplier and product identifiers; received quantities derive from immutable receipt lines. Prices, currency, payables, payment, tax, approval chains, and accounting remain outside this increment; see [Supplier orders and stock receiving](PURCHASING_ALPHA.md).

**Job material usage increment:** Issue #109 records quantity-only stock issues against organization jobs. Immutable job issue history links to inventory movements and is visible from the job and inventory views. Stock is reduced immediately; reservations, costing, valuation, invoicing, and accounting are not included. See [Synthetic Inventory Alpha](INVENTORY_ALPHA.md).

**Inventory reorder increment:** Issue #115 adds product-level reorder points, aggregate on-hand visibility, and purchasing suggestions that subtract outstanding incoming quantities. Managers can prefill an editable supplier-order draft and must choose the supplier; nothing is issued automatically. See [Synthetic Inventory Alpha](INVENTORY_ALPHA.md) and [Supplier orders and stock receiving](PURCHASING_ALPHA.md).

**Job material reservation increment:** Issue #119 adds tenant-scoped, location-specific reservations, explicit release, partial consumption through job material issues, and available-stock protection against other stock decreases. Reservation changes share the organization lock used by stock movements. See [Synthetic Inventory Alpha](INVENTORY_ALPHA.md).

## P3 — Payments and reconciliation

- Begin with explicit manual payment recording and allocation.
- Add idempotent provider events only after a provider route, onboarding needs, and failure recovery are understood.
- Cover partial, unmatched, duplicated, delayed, reversed, refunded, and overpaid cases.
- **Acceptance:** balances use exact arithmetic; event retries do not duplicate records; unresolved exceptions are visible and recoverable.

**Implementation progress:** Issue #15 shipped manual receipts, same-customer/same-currency invoice allocations, derived balances, and auditable reversal paths in v0.6.0. Issue #19 shipped tenant-scoped finance CSV exports that preserve unmatched and reversed states in v0.7.0. Issue #23 established the provider-neutral event boundary, and issue #25 documented tenant credential safeguards. Issue #29 selects Safaricom Daraja M-Pesa Express/STK Push as the provisional first sandbox connector for Kenya-focused tenant invoice collections; Flutterwave is deferred for later evaluation. Issue #31 implements sandbox-only STK attempts, durable callbacks, M-Pesa Express Query verification, and finance receipt capture through the existing manual workflow. Issue #55 adds finance UI for starting and tracking sandbox attempts. Automatic ledger receipt creation is deferred until the query response contract is confirmed with the Daraja simulator. No live payments are shipped. ADR-004 recommends Cloud Run + Cloud SQL for PostgreSQL + Secret Manager as the initial hosted reference path; Kubernetes is optional, and region/sizing still require readiness and cost review. Live tenant shortcode connections remain blocked until Safaricom confirms the SaaS model and merchant onboarding in writing. Next, validate the query response contract using sandbox data.

## P4 — Evaluation readiness

Before real business data is introduced, choose the actual region and database sizing, document the support process and recovery objectives, configure monitoring and backup retention, complete a database restore rehearsal and secret rotation/access review, and obtain Safaricom's written approval of the tenant account model before enabling live Daraja connections. Kubernetes is not a prerequisite.

**Implementation progress:** Issue #36 reviews API and finance-export tenant/role boundaries and sensitive logging, and closes customer-directory and quotation read-access gaps for employee/finance roles. Issue #37 adds purpose-bearing, time-limited tenant/data-scope grants for read-only Django Admin support access with view auditing. Issue #38 implements database-shared login/callback limits, payload bounds, unmatched callback retention, and a cleanup command. Issue #42 adds a PostgreSQL backup/restore runbook and a verified local synthetic-data rehearsal. Issue #95 adds a gated, dry-run-first accepted-evidence expiry operation with an explicit cutoff recorded in audit metadata, plus verification that cleanup removes restored bytes when a deletion tombstone is present. Issue #97 documents the provider-neutral independent deletion-ledger contract. Issue #99 adds a local synthetic SQLite journal and restore-replay command; its journal is not an independently protected production ledger. Issue #101 compares production ledger patterns and object-store deletion controls and defines the recovery gate and rehearsal matrix. Issue #111 adds complete member-role regression coverage for job material issue writes. Issue #113 extends the internal alpha security review with six-role read/write coverage for inventory and supplier purchasing workflows. Hosted backup/PITR, provider and region choice, customer retention decisions, independent checkpointing, storage-specific purge guarantees, monitoring, alerting, and recovery cutover remain outstanding.

- Complete organization/role security review, export, deployment-specific backup/restore, monitoring, and recovery documentation.
- Define a bounded field evaluation, responsibilities, privacy safeguards, rollback, baseline, and support process.
- **Acceptance:** qualified reviewers accept the safeguards and a restore rehearsal succeeds before real business data is used.

## Later candidates, not committed scope

Merchant-owned storefronts, inventory, POS, purchasing, recurring billing, advanced HR/attendance, recruitment, payroll, native apps, analytics, marketplace, and multi-country tax/payroll remain future candidates. Reprioritize them only when implementation learning, available information, specialist review, and delivery capacity justify the work.
