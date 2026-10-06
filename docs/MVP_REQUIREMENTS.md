# MVP Requirements

**Status:** Draft scope for validation and prototype; not an implementation commitment  
**Last updated:** 6 October 2026

## Product boundary

The MVP prototype tests a connected job-to-cash workflow for an as-yet-unselected service-business segment. The product has global ambitions; Kenya is one candidate beachhead market, not a product boundary. Market-specific tax, payroll, payment and regulatory behavior must be validated separately before it is promised or built.

**Customer → quotation → accepted job → staff assignment → time/expenses → invoice → payment allocation → reconciliation → owner reporting.**

The first segment remains unvalidated. Distributor stock workflows are a comparison, not part of this service-business MVP unless evidence changes the decision. Finance scope must be finalized with customers and an accountant. Invoicing and payment reconciliation must not be marketed as a full accounting system unless a balanced ledger and required reports are delivered and verified.

## Roles

- **Business owner:** configure company, invite users, see agreed operational and receivable summaries.
- **Sales user:** maintain customer records and prepare/send quotations within assigned scope.
- **Operations manager:** accept work, assign staff, review time and expenses.
- **Finance user:** issue invoices, record/allocate payments, resolve reconciliation exceptions, export records.
- **Employee:** view own assignments, submit time/expenses, request leave, view only permitted personal records.
- **Tridim support operator:** time-limited, audited access only when authorized and required; no default access to salary or customer data.

These are starting profiles, not substitutes for organization-scoped policy. Each business record and file belongs to an organization and, where applicable, a legal entity. Users belong to organizations through explicit memberships.

## User journeys and acceptance criteria

### Company, membership and authorization

- Owner creates a company, legal entity, currency/time-zone preferences, and initial users.
- An invitation binds to the intended organization and role after acceptance.
- A user cannot view or mutate another organization’s records through pages, APIs, search, exports, files, jobs or guessed identifiers.
- Employee access to HR records is limited to permitted personal records; confidential HR and salary fields require explicit permission.
- Sensitive changes record actor, organization, object, time and action.

### Customer and quotation

- Sales creates and updates customer/contact records with duplicate-detection support.
- A quotation records customer, lines, quantities, currency, applicable taxes/discounts, validity, status and history.
- Authorized acceptance records who accepted and when.
- An accepted quotation creates at most one linked job without duplicating customer or line data.
- Rejected, expired, withdrawn and superseded quotations remain distinguishable in history.

### Job, assignment, time and expense

- An accepted job has an owner, status, planned work, assigned staff and customer link.
- Manager assigns or reassigns staff; changes are visible to affected users and retained in history.
- Employees submit time and expense entries against authorized jobs with date, amount, currency and required evidence.
- Managers approve, reject with reason, or request correction. Submitted entries are not silently overwritten.
- Approved costs are available for job reporting and invoicing decisions but are not automatically treated as accounting expenses without an agreed accounting design.

### Invoice and payment

- Finance creates an invoice from an accepted quotation/job, retaining links and preventing unintended duplicate invoices.
- Issued invoices have clear state, unique numbering policy, due date, currency, totals and audit history.
- Initial internal invoice numbering uses a per-organization calendar-year sequence; voided numbers remain reserved. Until organizations have a timezone setting, the calendar year follows the application timezone (currently UTC). This internal default does not claim to meet jurisdiction-specific numbering rules.
- Internal invoice totals preserve exact quantity × unit-price products to five decimal places; internal allocations compare amounts at that precision. Currency-specific rounding must be defined before customer-facing invoice documents or provider integrations.
- Changes after issue use controlled cancellation, credit-note or adjustment flows rather than silent edits.
- A payment can be recorded manually or imported through a verified provider route; it can be allocated subject to explicit rules.
- A manual receipt records customer, date received, positive amount, three-letter currency, method, optional reference, actor, and timestamp. A client idempotency key prevents retry duplicates.
- Payment and allocation values use exact decimal arithmetic to five places in this internal workflow. Payment and invoice currencies must match; currency-specific rounding and settlement behavior must be defined before customer-facing financial documents or provider integrations.
- Allocations may be partial and may cover multiple invoices for the same organization and customer. Active allocations cannot exceed the unapplied payment amount or the invoice's outstanding amount. An overpayment remains unapplied until it can be explicitly allocated.
- Reversals require a reason and retain the actor and timestamp. Active allocations must be reversed before a payment can be reversed or an invoice can be voided; reversals do not delete the original receipt or allocation.
- Repeated delivery of the same provider event cannot create a second payment or allocation. Event and processing result are traceable.
- Partial, over-, delayed, reversed, refunded, unmatched and disputed payments have distinct states or exception records.
- Unmatched receipts remain visible and do not reduce receivables until allocated.
- Customer balance uses exact decimal arithmetic and explicit currency/rounding rules over issued invoices and valid allocations/adjustments.

### Reporting and export

- Owner sees jobs by agreed status and outstanding receivables with a documented definition.
- Do not label an issued invoice total as outstanding until recorded payments, credits and adjustments are applied under explicit allocation rules.
- Finance exports invoice, payment, allocation and reconciliation records in a documented format.
- The current CSV export format and its balance/state definitions are documented in `FINANCE_EXPORTS.md`.
- Reports show currency, date range, as-of time and definitions. Do not label invoice totals as recognized revenue without an accounting policy.
- Exports enforce the same tenant and role restrictions as the application.

### Core HR

- Authorized HR/owner user maintains employee, department and employment-status records.
- Employees submit leave requests; approvers decide with recorded outcome and date.
- Employees see only allowed personal profile and leave information.
- Payroll calculations, payslips, tax submissions and statutory filing are out of MVP scope until separately validated and approved.

## Nonfunctional requirements

### Financial integrity

- Use exact monetary types; never binary floating point for stored/calculated money.
- Define and verify invoice, allocation, credit, reversal, currency and rounding rules before pilot.
- Commit related database state transitions atomically. External provider calls are outside the database transaction; use durable event records, idempotency, retries and reconciliation.
- Do not delete issued financial records; corrections retain an audit trail.

### Security and privacy

- Enforce least privilege, secure authentication/session handling, MFA for privileged accounts, encrypted transport, protected secrets and restricted audit access.
- Apply tenant scoping across APIs, files, workers, cache keys, search, logs, exports and support tools.
- Minimize personal data; define retention, deletion, access/export and incident processes before production use.
- Default to no sensitive HR/financial offline device cache. Offline drafts require explicit conflict and device-loss design.

### Reliability, usability and operations

- Define service, recovery-point and recovery-time targets with pilot customers before promising them.
- Document deployment, migrations, backup, restore, monitoring, support access and incident response before field evaluation.
- Monitor failed jobs, duplicate/late provider events, unmatched payments, backup/restore status and workflow errors.
- Responsive web supports agreed owner, finance, manager and employee tasks on common phone and desktop sizes.
- Show actionable errors and recoverable states. Do not signal payment or tax success until the authoritative system confirms it.
- Container/Kubernetes deployment remains an implementation choice; it does not require a language or microservices.

## Out of scope

Comprehensive accounting beyond the confirmed evaluation boundary; payroll calculations; KRA eTIMS certification/submission; M-PESA production integration without onboarding and credentials; multi-vendor marketplace; pooled funds; wallet; manufacturing; full inventory/POS; advanced analytics; native apps; multi-country tax/payroll; and unverified compliance or availability claims.

## Core release scope

The initial release should provide a coherent, self-hostable version of the validated workflow: organization and role setup; customers, quotations, jobs, invoices, payment allocation and receivables; and documented import/export. The software license is still undecided. Security fixes, tenant isolation, auditability, privacy controls and customer data portability are core requirements.
