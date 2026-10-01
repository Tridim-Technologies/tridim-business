# Tridim Business Platform — Project Charter

**Status:** Working charter; strategy and assumptions are not yet validated  
**Last updated:** 1 October 2026  
**Parent company:** Tridim Technologies  
**Product name:** Tridim Business Platform  
**Short name:** Tridim Business

## Purpose and vision

Tridim Business Platform aims to help growing businesses run connected day-to-day operations in one place, with a global market ambition. Its long-term scope may include sales and CRM, jobs and projects, finance, people operations, inventory and merchant commerce.

The first sales beachhead is undecided. Kenya remains one candidate market, not the product boundary. Design the shared core for currencies, languages, time zones and legal entities, and implement country-specific tax, payroll, payment, privacy and reporting capabilities only after each market's requirements and support model are verified. Global-ready design does not establish compliance in any country.

**Positioning hypothesis:** “Keep your jobs, staff, invoices and collections connected without re-entering the same information across different tools.”

This is a product hypothesis, not a validated claim or public promise. Do not use Tandivaro or Kelvumo in new branding, repositories, package identifiers or public materials. The current Tridim Business name is a preference, not a trademark clearance result.

## Target-customer hypotheses

### Primary segment to investigate

Service businesses with approximately 10–75 employees are the primary segment hypothesis, initially technical support, installation, maintenance, consultancy and agency firms. Geography is open; Kenya is a candidate for initial research and launch, not a limit on the product. Potential buyers include owners, managing directors and finance or operations leads. Likely users also include sales staff, project managers, employees and bookkeepers.

### Comparison segment

Small distributors and wholesalers in accessible candidate markets. Compare their workflow friction, implementation needs and need for inventory before selecting the first segment.

### Separate hypothesis

Payroll-first software may address a real need, but correctness, statutory updates and specialist review make it a distinct and higher-risk area. Basic HR can be evaluated without promising payroll calculations.

These segments and buyer roles are research targets only. No customer demand, design partner, purchase commitment or market size has yet been established.

## First workflow and MVP boundary

The first workflow to test is:

**Customer → quotation → accepted job/project → staff assignment → time and expenses → invoice → payment allocation → reconciliation → owner reporting.**

The desired outcome is that an owner can see work in progress and outstanding balances, staff can see their assignments, and finance staff can follow the path from completed work to reconciled payment without reconstructing it across disconnected tools.

### Pilot essentials, subject to discovery

- Business setup, legal-entity and user structure, roles, permissions, approvals and audit history.
- Contacts, customers, quotations, invoices, status history and follow-ups.
- Jobs/projects, tasks, assignments, timesheets and expenses.
- Core HR records, departments, leave requests and approvals, onboarding checklists and employee self-service, with confidential HR access restricted.
- A single, clearly defined source of truth for invoices, payments and accounting entries; payment allocation, reconciliation and accountant-facing reports/exports.
- Controlled imports/exports, attachments, configuration and auditable change history.
- Responsive web experience; evaluate an installable PWA before committing to native apps.

Every included feature must trace to a demonstrated customer problem. The initial product should complete a narrow workflow reliably rather than claim broad module coverage.

### Explicit exclusions from the initial pilot

- Payroll calculations until rules are verified, effective-dated, independently checked and validated in parallel against an established process.
- A multi-vendor marketplace, pooled customer funds, split settlements or a Tridim wallet.
- Manufacturing, advanced inventory, POS, recruitment, appraisals, advanced attendance, assets, budgeting and advanced analytics unless discovery changes the priority.
- Simultaneous greenfield delivery of a full ERP, marketplace, payroll suite and commerce platform.
- Native Android/iOS apps unless observed pilot needs justify device integration, notifications or richer offline use.
- Country compliance, availability, savings, security certifications or service levels that have not been verified and demonstrated.

Merchant-branded storefronts remain a long-term product direction. Bring them into the first pilot only if the selected segment demonstrates a need; keep storefront identity and customer experience distinct from internal business administration.

## Foundation options and decision criteria

No implementation foundation has been selected. Compare both routes using the same end-to-end pilot workflow and evidence.

### Route A — Existing platform

Evaluate Frappe Framework, ERPNext and Frappe HR, extended through supported Tridim applications and integrations. Verify current licences and trademark rules, supported releases, database and deployment requirements, upgrade path, APIs, tenant isolation, security practices, mobile usability, and total cost. Prototype imports, permissions, document handling, payment exceptions, backups, upgrades and restoration. Prefer supported extension points and record the cost of any upstream divergence.

### Route B — Greenfield modular monolith

The founder’s preferred custom-build direction is **Python + Django + Django REST Framework + PostgreSQL + TypeScript/React**. Treat this as the leading custom-build hypothesis, not a final foundation decision. Evaluate it against Route A using the same workflow and acceptance criteria. Django Admin would be a restricted internal operations tool, not the customer-facing product; built-in authentication and model permissions do not replace organization-scoped authorization or tenant isolation.

Use explicit business operations for sensitive state changes such as quotation acceptance, invoice posting, payment allocation and leave approval. Add background workers and object storage only when the workflow demonstrates the need. FastAPI is not part of the current candidate set.

### Shared principles

- Start with a modular application and asynchronous workers; do not make microservices, Kubernetes, a service mesh, Kafka or multi-region active-active a default MVP requirement.
- Establish explicit domain ownership and interfaces for identity, sales, work, HR, finance, commerce and integrations.
- Separate deployment administration from customer business records. Assess isolation across requests, files, jobs, caches, exports and support tools; a separate database alone is not proof of isolation.
- Choose one operational and accounting system of record. Do not create competing ledgers across an ERP and a custom backend.
- Keep jurisdiction-specific rules and integrations in versioned localization packages; use exact monetary arithmetic, explicit rounding, idempotent event handling, auditable financial history and controlled reversals.

### Evaluation criteria

Score each route with evidence for workflow fit, permission and tenant-isolation quality, accounting/payment correctness, Kenya integration feasibility, licensing and trademark constraints, upgrade and extension burden, security and recovery, customer usability, implementation effort, operating cost, vendor/community sustainability and future localization. Record unknowns separately from observed results. The architecture decision is gated on a working prototype and documented trade-offs, not familiarity or feature count.

## Core product principles

- Keep the first release focused on the complete workflow defined above and the requirements in `MVP_REQUIREMENTS.md`.
- Keep organization separation, authorization, auditability, privacy, security fixes and data export in the core product.
- Prefer reusable, documented interfaces and avoid code duplication.
- Do not claim market fit, country compliance, security certification or production readiness without evidence.
- The license remains undecided. Review ownership, dependencies and obligations before public release.

## Roadmap

Milestones, dependencies, indicative effort and exit criteria are maintained in [`DETAILED_ROADMAP.md`](DETAILED_ROADMAP.md). Dates remain uncommitted until team capacity, foundation and prototype results are known.

## Principal risks, dependencies and mitigations

| Risk or dependency | Why it matters | Early response |
|---|---|---|
| Segment and workflow need are unvalidated | Building the wrong workflow creates sunk cost. | Compare service businesses with distributors through observed workflow interviews and concrete product examples. |
| Foundation fit and licence obligations are unknown | Poor fit or unclear rights can create upgrade, legal and maintenance costs. | Prototype both routes, review primary licence/trademark sources and track customizations. |
| Finance and payment state correctness | Duplicate, delayed or partial events can corrupt balances and trust. | Define source of truth, idempotency, reversals and exception handling; test reconciliation before pilot. |
| Kenya statutory and provider integrations change | KRA, payment and payroll processes may require current approval or specialist work. | Maintain dated official-source research and accountable owners; do not claim compliance before verification. |
| Tenant data exposure | A cross-tenant leak would cause serious customer harm. | Design and verify isolation for application, storage, jobs, exports, support and backup/restore paths. |
| Scope expands into a broad suite | Parallel modules delay a complete workflow. | Gate each module on customer evidence and protect the initial workflow boundary. |
| Brand availability is unresolved | The preferred name may conflict or be unavailable in relevant channels. | Treat the name as provisional; conduct formal name, domain, store and trademark checks before external commitment. |
| Existing Tridim repository is a company website with local changes | Product planning work could be mixed with unrelated site work. | Keep this charter isolated in its own documentation folder and preserve existing changes. |

Key dependencies include prospective customer access, foundation prototypes, current official Kenya requirements, payment-provider onboarding and credentials (if selected), verified licence terms, available budget and team capacity. None is assumed secured.

## Highest-impact unanswered assumptions

Resolve these in order during Stage 0 and Stage 1:

1. Which segment and reachable beachhead market have an urgent, frequent and costly end-to-end workflow?
2. Who uses the workflow daily, what current tools or spreadsheets are involved, and what concrete outcomes matter?
3. Does the proposed job-to-cash workflow require integrated bookkeeping and payment reconciliation from day one, or can an accountant-facing export suffice for the first evaluation?
4. Which country integrations are necessary for the first workflow, and what current provider or statutory requirements apply?
5. Can an existing Frappe/ERPNext foundation support the workflow with acceptable tenant isolation, upgrades, UX and extension burden compared with a modular monolith?
6. What delivery capacity is available for discovery, prototype and evaluation?
7. Is “Tridim Business” available for the intended software, domains and publishing channels after appropriate clearance?

## Immediate next documents

The core product documents are the validation plan, MVP requirements, foundation ADR, roadmap backlog and detailed roadmap. Keep them consistent with this charter, trace features to observed customer problems, and avoid a large speculative backlog before customer and foundation evidence exists.
