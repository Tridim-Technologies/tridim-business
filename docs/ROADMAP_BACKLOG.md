# Roadmap Backlog

**Status:** Evidence-gated planning backlog; no implementation estimates or issue tracker commitments  
**Last updated:** 1 October 2026

This backlog is limited to discovery, foundation fit and one job-to-cash workflow. Do not turn the long-term suite into a large speculative build plan before segment and foundation decisions.

## P0 — Discovery and definition

### P0.1 Compare service firms and distributors across candidate markets

- Recruit and conduct the proposed 20 workflow interviews.
- Capture recent examples, roles, current tools, duplicated entry, exceptions, pain frequency, switching barriers and adoption needs.
- **Acceptance:** evidence tracker completed with direct observations separated from opinions; counter-evidence and preferred segment decision recorded.
- **Dependency:** founder access to prospective businesses.
- **Market principle:** compare evidence from more than one candidate geography where access permits; do not generalize one country's interviews into global demand.

### P0.2 Map workflow and accounting boundary

- Map customer → quotation → job → time/expenses → invoice → payment allocation/reconciliation → reporting.
- Ask finance users/accountants when invoices, payments, tax records and accounting entries become authoritative.
- **Acceptance:** state model, exceptions and source-of-truth boundary reviewed; unresolved accounting questions assigned.
- **Dependency:** representative workflow interviews.

### P0.3 Establish decision assumptions

- Record team capacity, available user access, current systems and required integrations.
- **Acceptance:** unknowns have owners or are explicitly unassigned; no invented launch date.

## P1 — Foundation assessment

### P1.1 Frappe/ERPNext fit prototype

- Configure or extend only enough to demonstrate the same acceptance workflow.
- Test imports, roles, organization separation, payment exceptions, documents, mobile usability, upgrade path, backup and restore.
- Record exact versions, license files, dependencies, customizations and deployment effort.
- **Acceptance:** evidence and gaps scored against ADR-001; no branding or relicensing assumptions.

### P1.2 Custom Django fit prototype

- Build a narrow Django + Django REST Framework + PostgreSQL slice with a TypeScript/React client.
- Model tenant membership, quotation acceptance, job linkage, invoice, payment idempotency, balance and audit history.
- **Acceptance:** same user/failure scenarios as P1.1; development and maintenance effort recorded. This is a prototype, not production architecture.

### P1.3 Foundation decision

- Compare both prototypes with identical criteria and actual effort.
- **Acceptance:** ADR-001 updated to an accepted decision with rationale, license-review status, operating assumptions and rejected alternatives.

## P2 — Field evaluation readiness, only after P0/P1 gates

The core workflow and safety requirements below define the initial product scope. Security, tenant separation, audit and export are core requirements.

### P2.1 Evaluation plan and data safeguards

- Bound workflow, participants, data roles, retention, migration, rollback, training and success measures.
- **Acceptance:** evaluation participants and scope are agreed; no unsupported service/compliance claims.
- **Market gate:** select the evaluation country based on access, workflow fit and local requirements. Kenya remains a candidate, not an automatic default.

### P2.2 Tenant, roles and audit foundation

- Implement verified organization/entity ownership, role policies, audit trail, file/job/export controls and support-access logging.
- **Acceptance:** cross-tenant and unauthorized-role cases deny access across interfaces and background paths.

### P2.3 Core job-to-cash workflow

- Implement customers, quotations, jobs, assignments, time/expenses, invoices, allocations and receivables reporting.
- **Acceptance:** pilot users complete agreed real transactions; state changes and corrections remain auditable.

### P2.4 Payment exception handling

- Implement manual/provider event ingestion, idempotency, delayed/duplicate delivery handling, partial allocation, unmatched receipts, reversal/refund and reconciliation.
- **Acceptance:** repeated events cannot duplicate postings; unresolved exceptions are visible and recoverable.
- **Dependency:** confirmed provider route, credentials and required approval if in scope.

### P2.5 Evaluation migration and recovery

- Import only active customers, employees, open jobs, outstanding invoices and required balances.
- Reconcile totals against source exports; document rollback/parallel operation.
- **Acceptance:** customer-approved reconciliation and demonstrated restore/recovery procedure.

## P3 — Public release readiness

After successful field evaluations: document installation, configuration, upgrades, monitoring, restore, contribution and release procedures. Acceptance: new users can deploy the product, complete the documented core workflow, export their data and recover from a restore rehearsal without project-specific code changes.

## Later candidates, not committed backlog

Merchant-owned storefronts, inventory, POS, purchasing, recurring billing, advanced HR/attendance, recruitment, validated payroll, native apps, advanced analytics, marketplace and multi-country tax/payroll remain uncommitted candidates. Prioritize each only when user evidence, specialist review and capacity justify it. Multi-vendor marketplace and pooled funds are outside the MVP.
