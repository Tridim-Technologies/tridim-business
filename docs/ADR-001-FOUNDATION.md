# ADR-001: Product Foundation and Language

**Status:** Proposed; final choice is gated on foundation assessment and prototype  
**Date:** 1 October 2026  
**Decision owners:** Founder; legal, accounting and security review owners unassigned

## Context

Tridim Business Platform has a global product ambition. The initial customer segment and first market are undecided; Kenya is one candidate. The initial workflow to validate is customer → quotation → job → time/expenses → invoice → payment allocation/reconciliation → reporting. No demand, customer, delivery team, budget or production system has been established.

Two different strategies are under review: adopt and extend an existing business application, or build a focused custom product. The founder’s preferred custom-build stack is Python, Django, Django REST Framework, PostgreSQL and TypeScript/React. FastAPI is excluded from consideration by founder preference. Go and Rust are not proposed for the business core; Kubernetes does not require either language.

## Options

### A. Frappe Framework + ERPNext + Frappe HR

Use the existing applications as the operational system of record, with supported Tridim applications and integrations. This may avoid recreating mature workflows. Fit, usability, extension cost, upgrade path, tenant isolation, current supported versions, Kenya workflows and license implications must be demonstrated.

Frappe’s official policy lists Frappe Framework as MIT and ERPNext as GPLv3; it says other applications are governed by their own repositories. Frappe HR’s repository identifies GPL-3.0. These are separate components and licenses. Review exact versions, dependencies, extensions, trademarks and distribution model before product or repository decisions.

### B. Custom modular monolith

Python + Django + Django REST Framework + PostgreSQL + TypeScript/React. Django’s ORM, migrations, authentication and internal admin can reduce basic application assembly. Django Admin is an internal operations tool, not the customer experience. Model permissions alone do not enforce organization-specific access. Build explicit domain operations, tenant-scoped authorization, auditability and financial invariants.

Keep business modules in one deployable application initially, with explicit domain boundaries. Add workers/object storage only when requirements demonstrate need. Avoid a separate service per domain.

### C. Other greenfield languages/frameworks

Not an active evaluation path at this stage. Reopen only if the prototype identifies a specific limitation or team/product constraint that the selected route cannot meet.

## Recommendation

**Provisional recommendation:** evaluate Option A against the agreed end-to-end workflow; treat Option B as the preferred custom-build baseline. If Frappe/ERPNext cannot meet workflow, tenant/security, upgrade, licensing and UX criteria at acceptable cost, proceed with a Django modular monolith.

This is not approval to begin full implementation, choose a production host, publish an open-source license or claim compliance. Do not combine ERPNext and Django as coequal backends or maintain two ledgers. If a React interface is tested against Frappe, explicitly cost the API/auth/permission/upgrade work.

## Core repository and license

The local `tridim-business` directory is initialized as a Git repository on `main`; its GitHub remote is configured but has not yet been verified or pushed. The company website remains in its separate repository. The software license and public release readiness remain undecided. Review ownership, dependency licenses, trademarks and distribution obligations before publication.

## Prototype and evaluation criteria

Demonstrate the same thin vertical slice on the existing-platform and custom Django routes:

1. Create an organization, owner, finance user, manager and employee.
2. Create a customer and quotation; accept the quotation and create a linked job.
3. Create an invoice and record a payment.
4. Deliver the same external payment event twice and prove it creates one payment/allocation.
5. Show the correct outstanding balance to an authorized user; deny cross-organization and unauthorized-role access.
6. Simulate failed processing and recovery; demonstrate backup/restore of prototype data.

Score both routes with evidence for workflow completeness, correctness, user task completion, tenant isolation, license/trademark constraints, integration feasibility, maintainability, upgrade effort, security, recovery, development time, ongoing cost and administration/support effort. Use identical acceptance criteria.

## Consequences and follow-up

- Python + Django is the baseline custom stack, not yet the final platform choice.
- TypeScript + React is the leading product web-client direction; choose exact routing/rendering tools after prototype needs are known.
- PostgreSQL is the proposed custom database; accounting source-of-truth and ledger scope require customer/accountant validation.
- Broker, hosting, Kubernetes, tenancy deployment model, open-source license and mobile strategy remain open.
- Legal/accounting review and prospective design partners are dependencies; owners are unassigned.

## Primary references checked 1 October 2026

- Frappe licensing/trademark policy: https://docs.frappe.io/legal/others/license-and-trademark
- Frappe HR repository/license: https://github.com/frappe/hrms
- ERPNext licensing: https://frappe.io/erpnext/license-trademark
- Django documentation (models, migrations, admin, auth): https://docs.djangoproject.com/en/6.0/
- OSI Open Source Definition: https://opensource.org/osd
