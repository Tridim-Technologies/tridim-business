# Build and Field Validation Plan

**Status:** Implementation checks defined; no customer or production validation is claimed

**Last updated:** 1 October 2026

## Starting assumptions

- The first product scope is a service-business job-to-cash workflow: customer → quotation → accepted job → invoice → payment allocation/reconciliation → owner visibility.
- Service firms of roughly 10–75 employees are the initial working profile. It is not validated demand or a market-size estimate.
- The product has a global ambition. The first operating market and any country-specific integrations remain open.
- Django, Django REST Framework, PostgreSQL, and React/TypeScript are the founder-selected implementation direction recorded in [ADR-001](ADR-001-FOUNDATION.md).
- Invoicing and payment reconciliation do not imply a general ledger, tax compliance, or accounting recognition.

## Internal build checks

Each increment should have automated checks and documented manual acceptance evidence appropriate to its scope.

### Identity and organization boundaries

- A user can access only organizations where they have a membership.
- Customer reads, creates, updates, deletes, search, exports, and later background operations apply the same organization scope.
- A guessed organization or record identifier cannot cross the authorization boundary.
- Role restrictions are enforced by the API/domain layer, not only by hidden interface controls.
- Organization creation and membership assignment are explicit, auditable operations.

### Job-to-cash integrity

- An accepted quotation creates at most one linked job when requests are retried.
- Invoices and payments use exact decimal values and explicit currency rules.
- Repeated payment events cannot create duplicate payments or allocations.
- Partial, unmatched, delayed, reversed, refunded, and corrected states remain visible and recoverable.
- Issued financial records are corrected through auditable actions, not silent edits.
- Reports state their definitions and as-of time; operational totals are not presented as recognized revenue without an agreed ledger policy.

### Engineering and operations

- Migrations apply cleanly against PostgreSQL and tests run against the supported test database.
- Errors and logs do not expose secrets or unnecessary personal/financial data.
- Export respects the same organization and role checks as the application.
- Backup and restore, dependency updates, monitoring, and recovery procedures are documented before any real-data evaluation.
- Tests use synthetic data only.

## Field evaluation gate

Before any real business data or live operation, define a bounded evaluation with named participants and agreed safeguards. This is a later product-use validation step, not a prerequisite to beginning the internal build.

| Gate | Evidence required before evaluation | Pass condition |
|---|---|---|
| Scope and responsibilities | Users, tasks, data roles, support owner, retention, rollback | Agreed and documented before real data is introduced |
| Workflow completion | Customer through quotation, job, invoice, payment, and reconciliation | Agreed real transactions complete with traceable outcomes |
| Financial integrity | Duplicate, partial, delayed, unmatched, reversed, and corrected cases | No duplicate posting; exceptions are visible and recoverable |
| Tenant and role safety | Cross-organization and unauthorized-role attempts | Access is denied across UI, API, and exports |
| Recovery | Backup and restore rehearsal | Records can be restored and reconciled against an agreed baseline |
| Adoption and outcome | Baseline, training, support effort, task completion | Reviewed with participants; no unsupported savings or service claims |

Set numeric success measures only after the specific workflow and a baseline are agreed. Do not claim market fit, jurisdictional compliance, production readiness, or service levels from internal tests.
