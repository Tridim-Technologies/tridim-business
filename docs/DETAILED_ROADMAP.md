# Tridim Business — Core Product Roadmap

**Status:** Founder-directed build sequence; dates and staffing are not committed

**Last updated:** 20 October 2026

**Product ambition:** Global; Kenya remains a candidate market

## Roadmap principles

- Build from the existing MVP requirements and current product direction; maintain assumptions explicitly.
- Complete a narrow job-to-cash workflow before expanding into a broad ERP.
- Treat the static HTML prototype as a discussion aid only; it has synthetic data and no backend.
- Use the accepted Django/DRF/PostgreSQL and React/TypeScript foundation. Do not maintain parallel framework implementations.
- Tenant isolation, authorization, auditability, privacy and data portability are baseline requirements.
- Synthetic scenarios validate implementation behavior, not customer demand. Real-data evaluation has separate readiness gates.
- Global-ready design does not prove compliance in any specific country.

## Milestone map

| ID | Milestone | Exit evidence |
|---|---|---|
| M0 | Repository and decision setup | Public core repo, separate enterprise docs, issue workflow, package/release automation and roadmap are usable |
| M1 | Application foundation | Sign-in, organization membership and customer directory work locally with tenant/role tests |
| M2 | Customer to accepted job | Quotes have controlled status transitions and create no duplicate jobs |
| M3 | Job delivery to invoice | Assignments and delivery status link to invoices with auditable corrections |
| M4 | Payments and owner visibility | Exact balances, allocation/reversal handling and useful receivable views work in synthetic scenarios |
| M5 | Internal alpha readiness (local synthetic baseline complete; hosted/real-data gates deferred) | Export, access review, backup/restore, monitoring and operating instructions are reviewed |
| M6 | Bounded field evaluation readiness | Privacy/security safeguards, support, rollback, baseline and participant agreement are in place before real data |
| M7 | Repeatability and expansion decision | Installation/support are repeatable; evidence and capacity support the next market or module |

## Current implementation status

- **M0–M2:** Foundation and customer-to-job workflow are implemented in the existing releases.
- **M3:** Job delivery, invoice issuance, correction history, and owner/finance invoice visibility are complete in v0.5.0. Issue #47 adds job time entry submission and manager approval. Issue #49 defines the provider-neutral evidence policy in [ADR-005](ADR-005-EXPENSE-EVIDENCE-HANDLING.md); issue #51 defines the [expense claim MVP workflow](EXPENSE_CLAIM_MVP_WORKFLOW.md); issue #53 implements the [synthetic claim core](EXPENSE_CLAIM_ALPHA.md); issue #61 adds a gated local synthetic evidence path. Issue #103 adds injectable storage/journal contracts and synthetic failure-injection coverage for deletion orchestration. The contract is not a production adapter; real data remains gated on production storage, exact-generation purge, independently protected checkpoints, isolated parsing/scanning, retention, support, backup, and jurisdiction-specific decisions. Time and claims do not automatically create invoice charges or accounting entries.
- **Core HR:** Issue #59 adds a minimal employee directory linked to existing organization memberships, with manager-maintained work profiles and employee read access to active profiles. Issue #87 adds employee leave requests and auditable manager decisions without leave balances, statutory policy, payroll, or sensitive medical records. Issue #89 adds role-bounded organization invitations and signup/sign-in acceptance. Issue #91 adds optional SMTP-backed invitation email with a manual-link fallback; mailbox verification remains separate work.
- **Inventory:** Issues #105 and #119 add an organization-scoped catalog, locations, immutable stock movements, and location-specific job reservations. On-hand derives from movement history; available stock subtracts active reservations. Direct stock decreases respect these allocations, and job issues can consume reserved quantities partially. Costing, tax, and accounting remain out of scope. See [Synthetic Inventory Alpha](INVENTORY_ALPHA.md).
- **Supplier purchasing:** Issue #107 adds tenant-scoped suppliers, draft and issued orders, partial/full receipt history, and atomic links from receipts to inventory movements. Supplier and product details are snapshotted on orders. Pricing, currency, payables, payment, approval chains, tax, and accounting remain out of scope. See [Supplier orders and stock receiving](PURCHASING_ALPHA.md).
- **M4:** Manual receipts, same-customer/same-currency allocations, derived balances, and auditable reversals shipped in v0.6.0 through issue #15. Issue #19 shipped finance CSV exports for external review in v0.7.0. Issue #23 records the provisional first-provider sandbox direction and event/recovery contract in [ADR-002](ADR-002-PROVIDER-PAYMENTS.md); issue #25 records tenant credential lifecycle and secret-storage safeguards in [ADR-003](ADR-003-PAYMENT-CREDENTIAL-SECURITY.md). Issue #31 adds sandbox-only Daraja M-Pesa Express attempts, callbacks, and checkout-query verification, with receipt capture remaining in the existing finance workflow until the query response contract is confirmed against the simulator. Issue #55 adds the invoice UI for initiating and tracking sandbox attempts. No live payments are enabled. Confirm provider account-connection terms and the deployment/secret-manager choice before any live integration. Refunds, automated matching, and broader reconciliation remain future work.
- **M5:** The local synthetic baseline is complete: tenant/role and support-access reviews, local backup/restore rehearsal, endpoint safeguards, synthetic evidence handling, the executable readiness gate, and the local operating checklist are documented and covered by regression or quality checks. Hosted recovery, telemetry, scheduled jobs, independent evidence checkpoints, production storage/retention, and real-data evaluation remain deferred and keep M6 closed.

## M0 — Repository and decision setup

**Objective:** Make the core project understandable and ready for controlled implementation.

**Work:** maintain the core product repository and its documentation; keep enterprise-specific documentation in the separate enterprise repository; establish semantic release and GitHub Actions; record decisions on name, market, license and capacity; use issues and Conventional Commits to manage work.

**Exit:** contributors can identify current assumptions and the next issue; no customer data or secrets are committed; repository access and default branch are verified.

## M1 — Application foundation

**Objective:** Provide a secure starting point for organization-based business records.

**Work:** implement Django/DRF backend, React/TypeScript frontend, local setup, session sign-in, organization/membership models, role-aware workspace selection and customer list/create; add cross-organization and unauthorized-role tests; provide synthetic-data instructions.

**Exit:** a developer can run the app; an authenticated member can use the permitted customer workflow; guessed or foreign organization identifiers disclose no customer data; local checks and CI pass.

## M2 — Customer to accepted job

**Objective:** Make customer and quotation records flow safely into work.

**Work:** customer lifecycle/search and duplicate review; quotations with line items, revisions, expiry and explicit acceptance/rejection; audit history; idempotent job creation from accepted quotes.

**Exit:** synthetic scenarios exercise quote edits and repeated acceptance without duplicate jobs; organization/role rules hold across API operations.

## M3 — Job delivery to invoice

**Objective:** Connect accepted work to delivery and receivables.

**Work:** job ownership/status, assignment and delivery notes; time entry submission and manager approval; define private expense evidence handling and the MVP claim workflow, then build the synthetic claim core and a gated local evidence path; keep real evidence disabled until ADR-005 production and operating controls are verified; issue invoices through a defined source of truth; preserve controlled correction history; provide basic owner/finance views.

**Exit:** job and invoice links are explainable and exportable; invoices are not presented as full accounting without an agreed ledger and reporting model.

## M4 — Payments and owner visibility

**Objective:** Make collection states and outstanding balances dependable.

**Work:** begin with manual payment entry and allocation; support partial, unmatched, overpaid, delayed, reversed and refunded cases; add an external provider only after onboarding, event semantics and recovery are understood; expose clear as-of dates and definitions.

**Exit:** exact arithmetic and transactional updates are verified; retries do not duplicate events; corrections remain auditable; unresolved exceptions are visible.

## M5 — Internal alpha readiness

**Objective:** Support controlled internal use with synthetic records.

**Implementation progress:** Issue #36 reviews tenant and role boundaries across APIs/exports and sensitive logging; it closes employee access to the full customer directory and employee/finance access to quotations. Issue #37 adds time-limited, purpose-bearing organization/data-scope grants for read-only Django Admin support access and audits support list/detail views. Issue #38 implements database-shared login/callback limits, bounded payloads, unmatched-callback retention, and a cleanup command. Issue #42 adds a PostgreSQL backup/restore runbook and a verified local synthetic-data rehearsal. Issue #44 adds minimal liveness/readiness endpoints and a monitoring/incident runbook; Cloud Monitoring and Cloud Logging are the preferred future direction but are not configured. Issue #65 records internal-alpha planning targets of RPO up to 24 hours, RTO by the next business day, and a seven-day recovery window. Issue #67 consolidates current local evidence and readiness gates. Issue #69 adds an audit for platform-superuser list/detail reads of tenant models in the support-scoped Django Admin. Issue #95 adds a dry-run-first explicit cutoff and audit metadata for expiring accepted synthetic evidence, plus cleanup verification when a deleted-object tombstone survives a local restore. Issue #97 documents the provider-neutral independent deletion-ledger and restore-replay design. Issue #99 adds a local synthetic SQLite journal, pending-deletion state, idempotent purge ordering, and a replay command for older local database/object-directory snapshots. Issue #101 compares production ledger patterns and object-store deletion controls and defines a restore gate and rehearsal matrix. Issue #132 adds an executable local readiness gate; issue #134 consolidates the repeatable [local synthetic operating checklist](M5_LOCAL_SYNTHETIC_OPERATING_CHECKLIST.md). These are not customer commitments; hosted backup/PITR configuration and target verification, telemetry setup, scheduled cleanup, customer-specific retention policies, independent production checkpointing, storage-specific purge guarantees, provider/region/adapter selection, recovery cutover, and real-data use remain outstanding.

**Work:** adversarial tenant/role checks across APIs and exports; data export; logs without sensitive data; dependency/update process; deployment-specific backup and restore rehearsal; monitoring; deployment and incident notes; known gaps.

**Exit:** synthetic core journeys pass; export is usable; recovery procedure is rehearsed; critical security and financial invariants have automated coverage.

## M6 — Bounded field evaluation readiness

**Objective:** Establish safeguards before any real business records are used.

**Work:** qualified privacy/security/accounting review as applicable; retention, deletion and support-access policy; restore rehearsal and recovery expectations; evaluation scope, support owner, baseline, rollback and data exit; provider or statutory approvals if relevant.

**Exit:** owners accept the safeguards, evaluation scope is agreed, and unresolved critical issues have been addressed. Defer real-data use if any control is unowned or unverified.

## M7 — Repeatability and expansion decision

**Objective:** Make setup and support repeatable, then prioritize expansion deliberately.

**Work:** standardize installation, upgrades, training, export and recovery; measure onboarding/support effort; consider a second market, payment connector, storefront, inventory or deeper HR only with a clear use case, local review where needed, owner and capacity.

**Exit:** users can be onboarded without bespoke code forks, and an explicit product decision supports the next investment. Payroll, marketplace, native apps and advanced ERP capabilities remain uncommitted.

## Cross-cutting requirements

| Workstream | Applies from | Required evidence |
|---|---|---|
| Product scope and assumptions | M0 | Docs/issues distinguish decisions, assumptions and demonstrated behavior |
| Architecture and code review | M1 | Domain boundaries, migrations, authorization and upgrade path reviewed |
| Finance integrity | M2 | Source of truth, exact arithmetic, idempotency and corrections defined before financial workflows |
| Security and privacy | M1 | Tenant isolation tests; qualified review before real-data use |
| Localization and legal | Before market-specific claims | Current authoritative requirements and accountable reviewer |
| Support and recovery | M5 | Backup/restore, incident and support-access procedure rehearsed |
| License and publication | Before public release | License choice and dependency obligations reviewed |

## Decision cadence

At each milestone, record evidence reviewed, criteria passed or unresolved, scope changes, decision owner and next step in the relevant issue or project document. Keep calendar estimates out until team capacity and dependencies are known. Use product feedback if it becomes available; it does not block building the agreed initial product.
