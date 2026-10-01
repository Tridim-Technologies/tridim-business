# Tridim Business — Core Product Roadmap

**Status:** Planning baseline; dates and staffing are not committed  
**Last updated:** 1 October 2026  
**Product ambition:** Global; the first customer segment and beachhead market are undecided. Kenya remains a candidate.

## Roadmap principles

- Deliver evidence in gates. A milestone advances only when its exit evidence is reviewed; calendar time alone does not pass a gate.
- Start with one complete job-to-cash workflow. Do not expand into a broad ERP before users complete the workflow repeatedly.
- Keep customer discovery active through prototype, pilot and repeatability work.
- Treat the current clickable HTML as a discussion aid only. It has sample data, no persistence, and is not the Django implementation.
- Compare the existing-platform route (Frappe/ERPNext) and custom route (Django + Django REST Framework + PostgreSQL + TypeScript/React) on the same user workflow before selecting a foundation. FastAPI is excluded by the user's direction.
- Keep the product implementation and its public documentation in this repository.
- Security, tenant isolation, auditability, privacy and data portability are baseline product requirements.
- Global-ready data design does not establish compliance. Tax, payroll, payments and statutory integrations are country-specific work gated by local verification.
- Any time ranges below are rough planning ranges for a small, focused team and exclude waiting for access, procurement, legal review and partner approvals. Re-estimate after capacity and foundation are known.

## Milestone map

| ID | Milestone | Indicative effort | Gate |
|---|---|---:|---|
| M0 | Project setup and decision register | 1 week | Scope, owners, repository intent and evidence records usable |
| M1 | Segment and workflow validation | 3–5 weeks | Repeated pain, buyer and beachhead hypothesis evidenced |
| M2 | Foundation and workflow fit decision | 2–4 weeks | One route selected from equivalent evidence; ADR accepted |
| M3 | Core design and thin-slice alpha | 6–10 weeks | One role can complete a safe end-to-end workflow in a controlled environment |
| M4 | Pilot readiness | 2–4 weeks | Security, financial integrity, recovery, support and pilot agreement ready |
| M5 | Field beta and learning cycle | 8–12 weeks | Real workflow completed, outcomes measured, next product decision recorded |
| M6 | Repeatable service and release | 6–10 weeks | Second/third customers served without bespoke forks or unsustainable support |
| M7 | Second-market or next-module decision | Evidence-gated | Local readiness and user evidence justify a specific expansion |

These phases are sequential where one depends on another. Documentation, repository hygiene, customer conversations and risk review can continue throughout. No launch date or delivery commitment is implied.

## M0 — Project setup and decision register

**Objective:** Make the current project understandable, reviewable and ready for controlled implementation.

**Work:**
- Preserve the seven existing strategy and discovery documents; add this roadmap as the single milestone view.
- Establish this repository as the home for the core product and its public documentation.
- Record decisions and owners for product naming, market, segment, foundation, license, and project capacity.
- Keep product documentation in the product repository's `docs/`, separate from the Tridim Technologies company website.
- Use the clickable workflow prototype to gather feedback; log observations separately from assumptions.

**Deliverables:** initialized local repositories; root orientation files; roadmap; decision log; prototype link; initial issue/backlog structure.

**Exit criteria:** new contributor can understand repository purpose and current non-decisions; no accidental secrets, customer data or unclear license claims are committed; GitHub access and remote existence are verified before publishing.

**Stop/adjust if:** repository or license review identifies a publication issue, or naming clearance changes the product name.

## M1 — Segment and workflow validation

**Objective:** Select a narrow first customer/workflow and a reachable beachhead market based on observed work and credible purchase evidence.

**Work:**
- Conduct about 20 structured workflow interviews as a learning target, not statistically representative research. Compare service businesses and small distributors; sample one or more reachable markets and record geography.
- Observe recent customer-to-cash examples, including documents/tools, duplicated entry, approvals, exceptions, who does the work, and how payment is matched.
- Interview owner/buyer, operations and finance roles; include businesses using spreadsheets, competing tools, and businesses that rejected or stopped using software.
- Map current-state and desired-state workflow, roles, authoritative records, errors and exception paths.
- Test prototype comprehension and workflow gaps. Do not represent prototype features as available software.
- Identify country-specific dependencies (tax, payroll, payments, data handling, language, currency, hosting expectations) without promising coverage.

**Deliverables:** anonymized evidence tracker; segment/market comparison; workflow map and exception inventory; user-role map; updated product risk register; go/no-go recommendation.

**Exit criteria:**
- At least one repeated, costly workflow problem is supported by concrete examples in a reachable segment.
- A named buyer role, user roles and purchase decision path are understood.
- A single workflow boundary and pilot market candidate are chosen, with contrary evidence documented.
- At least two plausible businesses agree to a concrete product-learning next step, such as reviewing a workflow prototype or supplying anonymized examples.
- Finance source-of-truth and accounting boundary are reviewed with a qualified practitioner.

**Decision:** proceed to M2, narrow/reframe the segment, or pause. If demand is weak, do not compensate by adding modules.

## M2 — Foundation and workflow fit decision

**Objective:** Choose the product foundation by proving the same narrow workflow and operating needs on the candidate routes.

**Work:**
- Build/configure only enough of the job-to-cash slice to compare Frappe/ERPNext with the custom Django + DRF + PostgreSQL + React/TypeScript route.
- Exercise customer, quote acceptance, one linked job, invoice, partial payment allocation and correction/reversal scenarios.
- Compare organization/tenant authorization, audit history, exact monetary arithmetic, imports/exports, responsive use, background processing needs, deployment/upgrade, backup/restore and supported extension points.
- Record total effort, customization debt, operational cost, license obligations and third-party dependencies with source references.
- Keep a modular monolith as the default custom route. Kubernetes/microservices are not prerequisites; choose deployment complexity from actual operations.

**Deliverables:** equivalent scenario walkthroughs; trade-off scorecard; updated `ADR-001-FOUNDATION.md`; license and trademark review plan; migration/data ownership note.

**Exit criteria:** one route is recommended with measured evidence; unresolved risks and cost are explicit; an accountable reviewer accepts the ADR; implementation, update and data-export path is credible.

**Decision:** commit to one route for the pilot. Do not build parallel production systems or maintain two copies of the domain model.

## M3 — Core design and thin-slice alpha

**Objective:** Implement a controlled, coherent product slice behind the chosen foundation.

**M3.1 Domain and authorization design**
- Define organization, legal entity, membership, role, customer, quotation, job, invoice, payment and allocation ownership.
- Specify status transitions, numbering, currency/rounding, tax extension points, audit events and correction paths.
- Threat-model tenant boundaries and support access before loading real customer data.

**M3.2 Product shell and access**
- Build sign-in, organization setup, invitation/membership, navigation and role-aware empty/error states.
- Enforce authorization in the service/API layer; do not rely on hidden UI controls.
- Define session, credential, recovery, privileged access and audit practices.

**M3.3 Customer and quotation**
- Create/search/update customer records; support duplicate review.
- Create, revise, send/export, accept, reject, expire and withdraw quotations with history.
- Prevent duplicate job creation on repeated acceptance requests.

**M3.4 Job delivery**
- Create job from accepted quotation with traceable lines and values.
- Assign owner/staff, status, dates and notes. Add time/expenses only if M1 confirms they are essential for the first value loop.
- Preserve edits and approvals in an audit trail.

**M3.5 Invoice and payment allocation**
- Issue invoices from the agreed source of truth; control post-issue corrections.
- Record payment events and allocate them to invoices with idempotency, partial/unmatched/overpayment states, and reversal handling.
- Make balances exact, explainable and exportable; never imply accounting recognition without an agreed ledger model.

**M3.6 Visibility and export**
- Show jobs, due invoices, received/unmatched payments and definitions/as-of dates.
- Provide authorized data exports and a basic import path; record export actor and scope.

**Deliverables:** deployable alpha in a non-production environment; clickable core journeys; architecture and data model notes; API/interface notes; seeded synthetic demo data; deployment, backup and restore procedure draft; known gaps.

**Exit criteria:** internal users complete the agreed synthetic scenarios; important financial and authorization invariants are demonstrated; core records export; no real customer data is used before M4 readiness.

## M4 — Pilot readiness

**Objective:** Make the narrow product safe and operable for a bounded user evaluation.

**Work:**
- Complete role/tenant tests by adversarially attempting cross-organization access through screens, APIs, search, files, exports, workers and support paths.
- Test duplicate, delayed, partial, unmatched, reversed and refunded payment scenarios; agree reconciliation procedure with finance reviewer.
- Define backup frequency, retention, restore target, recovery point/time expectations, incident contacts and restore rehearsal.
- Establish logging/monitoring without leaking sensitive data; document dependency/update and vulnerability handling.
- Finalize privacy/data-processing roles, collection minimization, retention/deletion/export, consent and support-access process for the selected market with qualified review.
- Confirm whether payment, invoicing or tax providers require onboarding, approval or certification; keep unapproved integration out of pilot scope.
- Agree evaluation users, workflow, baseline, support contact, success measures, training, migration, rollback and data exit in writing.

**Deliverables:** evaluation agreement and data plan; security and privacy checklist; verified backup restore; operational runbook; support boundaries; migration reconciliation sheet; evaluation scorecard and baseline.

**Exit criteria:** evaluation scope and participants are agreed; real-data safeguards are reviewed; restore rehearsal passes; tenant and financial integrity scenarios pass; support and rollback owners are known.

**Decision:** start with one bounded pilot. Defer production use if any exit item remains unowned or unverified.

## M5 — Field beta and learning cycle

**Objective:** Confirm that users can complete the workflow in real operations and identify product gaps.

**Work:**
- Migrate only agreed active records and reconcile counts/totals with the customer before use.
- Train each agreed role and collect support friction during first live use.
- Run real customer → quote → job → invoice → payment allocation workflow; record exceptions and recoveries.
- Compare pre-pilot and pilot measures: completion time, duplicate entry, invoice readiness, payment matching, overdue visibility, adoption by role, onboarding and support hours.
- Review open issues weekly with customer; prioritize workflow blockers, financial integrity and access control before cosmetic scope.
- Capture every requested feature with requester, evidence, frequency, value, affected segment and cost; no automatic feature commitments.
- Review ongoing use, workflow completion, user feedback and unresolved blockers.

**Deliverables:** evaluation usage and outcomes report; reconciled migration record; support/incident log; prioritized backlog; participant feedback; lessons for docs and product design.

**Exit criteria:** customer completes agreed recurring workflows; no unresolved critical financial/security issue; outcomes and limitations reviewed with buyer; real delivery/support cost measured; next-step decision recorded.

**Decision:** continue with a broader beta, refine the scope, or stop. Positive feedback without observed workflow use is not sufficient evidence.

## M6 — Repeatable service and release

**Objective:** Prepare a reliable, documented release that can be installed and maintained by users.

**Work:**
- Standardize installation, organization setup, migration, training materials, upgrades and data export.
- Define supported versions, upgrade cadence, release notes, deprecation policy, vulnerability response and support severity/response boundaries.
- Automate repeatable build, migration, backup, restore, monitoring and deployment tasks at a level justified by customer count.
- Separate customer configuration from code forks; require explicit approval and support economics for custom integrations.
- Document supported deployment options, installation, backup, restore, upgrade, export and contribution process.
- Confirm the selected license and publication readiness with appropriate review before release.

**Deliverables:** installation and recovery runbooks; supported release policy; stable configuration/interfaces; license decision; beta cohort review.

**Exit criteria:** evaluation users complete setup and use without custom code forks; installation and recovery processes are rehearsed; product data remains portable.

## M7 — Additional-market or next-module decision

**Objective:** Expand only when a specific market or module has user evidence and delivery capacity.

**Candidate work:** a second country, a validated payment connector, storefront/catalogue, inventory/POS, deeper HR, analytics or payroll. Treat these as separate investment cases, not automatic roadmap scope.

**Required case for every expansion:**
- Evidence of a repeated user problem and a clear use case.
- Complete workflow and data-boundary map.
- Market-specific legal, tax, payment, privacy, hosting and support review where relevant.
- Integration/provider prerequisites and failure/reconciliation path.
- Security, tenant, migration, maintenance and localization plan.
- Build and ongoing maintenance estimate compared with available capacity.

**Exit criteria:** leadership explicitly prioritizes the expansion with capacity, owner, budget and acceptance measures. Otherwise retain it as an uncommitted idea.

## Cross-cutting workstreams and ownership

| Workstream | Required through | Accountable role (assign before execution) |
|---|---|---|
| Customer discovery and product decisions | M1 onward | Product founder |
| Architecture, delivery and code review | M2 onward | Technical lead |
| Finance integrity and accounting boundary | M1 onward | Finance practitioner + product owner |
| Security, privacy and incident readiness | M2 onward | Security/privacy owner with qualified advisers |
| Localization and legal review | M1 onward per market | Market owner + qualified local counsel/adviser |
| Product scope and release decisions | M1 onward | Product owner |
| Support, onboarding and migration | M4 onward | Operations/customer success owner |
| Open-source licensing and repository policy | Before public push/release | Repository owner + legal reviewer |

Roles may be held by one person initially, but responsibility must be explicit. Unknown owners are blockers to the relevant gate, not silently assumed capacity.

## Release and decision cadence

- Hold a short weekly review of evidence, customer blockers, risks and next decision; record decisions in the docs/issues.
- At each milestone exit, publish a one-page gate note: evidence reviewed, criteria passed/failed, counter-evidence, scope changes, decision owner and next milestone.
- Revisit product scope after each beta cohort using observed workflow completion and user feedback.
- Revisit the market/segment when evidence differs materially; do not preserve earlier assumptions for consistency's sake.
- Keep operationally critical work ahead of feature expansion: access, backups, data integrity, export, support and recovery.

## Explicitly uncommitted

Product name/trademark clearance; first segment/country; foundation; production architecture; software license; global rollout sequence; release date; Kubernetes; native apps; payroll; accounting ledger scope; and certifications remain undecided until their gates pass.
