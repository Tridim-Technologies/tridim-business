# Validation Plan

**Status:** Proposed product research plan; no interviews are claimed
**Last updated:** 1 October 2026

## Decisions this research should inform

1. Choose the first segment and beachhead market: service businesses or small distributors/wholesalers; Kenya is a candidate market, not the only market.
2. Confirm the users, painful workflow, current tools, switching barriers and integration needs.
3. Determine whether the workflow requires a full accounting ledger or whether invoices, allocations, reconciliation evidence and accountant-facing exports are sufficient.
4. Set evidence-based criteria for the Frappe/ERPNext and custom Django foundation prototypes.
5. Identify users willing to review workflow prototypes and provide concrete feedback.

The target of about 20 focused interviews is a learning target, not statistically representative research. Proposed split: 10 service businesses and 10 distributors, recruited in one or more reachable candidate markets. Record geography explicitly; do not treat results from one country as proof of demand or compliance elsewhere. A practical alternative is to select one accessible beachhead for deeper interviews, while using a smaller number of comparison conversations in a second market.

## Recruiting criteria

Recruit active businesses in reachable candidate markets that resemble the proposed customer profile. For service businesses, prioritize technical support, installation, maintenance, consultancy and agency firms with roughly 10–75 employees. For distributors, recruit small wholesalers with enough order and payment activity to demonstrate stock and reconciliation workflows. Kenya remains an accessible candidate based on the earlier plan; do not make it a required or exclusive geography.

Interview people who own, approve or execute the workflow: owners/directors, operations/project managers, and finance/bookkeeping leads. Where possible, speak to more than one role at a business. Include spreadsheet users, current software users, and businesses that recently rejected or stopped using a tool. Avoid recruiting only friends, vendors or people who already favor the idea.

Ask before recording. Keep notes factual, minimize personal data, assign respondent IDs, and do not put sensitive customer or employee records in the research tracker.

## Interview guide

Start with a recent real example. Do not pitch the product first.

1. Tell me about the last customer order or service job you completed, from initial request through getting paid.
2. What records or documents were created, and who handled each step?
3. Where was information entered more than once? Can you show an anonymized example?
4. How do you know which jobs are in progress, delayed or ready to invoice?
5. What happens between sending an invoice and confirming payment has been received and matched?
6. What were the last payment, invoice, approval or reconciliation exceptions? How were they resolved?
7. How are staff assignments, time, expenses or leave recorded and approved?
8. Which tools, spreadsheets, accountants, payment providers or government systems are involved?
9. How often does the problem occur? What time, cash, service or management outcome does it affect?
10. What have you tried to change? What would prevent switching or adding a system?
11. Who approves a purchase, who uses the workflow weekly, and how is a software purchase decided?
12. What would a product trial need to show for you to use it in your regular work? What would prevent adoption?

Keep the discussion focused on observed work, task outcomes and adoption barriers. Do not present the concept as finished software.

## Review the workflow concept

Show the clickable concept only after hearing the user's recent workflow. Ask which fields or steps are wrong, what exception is missing, whether each role can complete their tasks, and what would make the flow hard to adopt. Record observations separately from opinions.

## Evidence record

Use the blank assets in [`docs/discovery/`](discovery/README.md) to record and synthesize interviews without repeating this guide. Keep only respondent IDs in working notes; store completed research records in an access-controlled private location outside this public repository. The repository should contain templates and aggregated, non-identifying conclusions only.

| Field | Notes |
|---|---|
| Respondent ID, date, segment, role | |
| Business size and workflow | |
| Recent example observed or described | |
| Current tools and duplicate entry | |
| Pain frequency and evidenced cost | |
| Invoice/payment/reconciliation exceptions | |
| HR, assignment, time or expense needs | |
| Buyer, users and decision process | |
| Integration and migration needs | |
| Switching barriers and alternatives | |
| Product feedback and concrete next step | |
| Evidence strength and follow-up | |

Label findings as observed, recalled, opinion or unverified. Separate direct quotes from interpretation. Aggregate patterns by segment, not respondent enthusiasm.

## Segment decision rules

Prefer a segment/market combination with stronger evidence of repeated workflow friction, reachable users, a complete narrow workflow, manageable product scope and verifiable obligations. A segment or country does not win because it requests more features.

Pause or narrow the proposition if interviews show no repeated pain, no meaningful workflow outcome, or a need for broad accounting/payroll/compliance work beyond available capacity. Record counter-evidence before building.

## Field evaluation scorecard

Use a small number of evaluation users after discovery supports the workflow. Installation alone is not a successful evaluation.

| Gate | Evidence | Pass condition |
|---|---|---|
| Evaluation scope | Named participants, agreed tasks and safeguards | Users and scope are agreed before any real data is introduced |
| Workflow completion | Customer to quote to job to invoice to payment allocation/reconciliation | Agreed real transactions complete with auditable results |
| Baseline and outcome | Time, duplicate entry, payment exceptions, visibility | Baseline and review data recorded; outcome reviewed with customer |
| User adoption | Owner, finance, manager and employee activity as applicable | Intended roles complete their agreed tasks in real work |
| Financial correctness | Duplicate, partial, delayed, reversed and unmatched cases | No duplicate posting; exceptions are visible and recoverable |
| Tenant and role safety | Cross-company and unauthorized-role attempts | Access is denied across application and exports |
| Setup and support effort | Installation, migration and questions | Actual effort and repeated sources of friction are recorded |
| Next product decision | Continued use, gaps and reasons | Decision and counter-evidence are documented |

Set evaluation-specific numeric measures after collecting a baseline. Do not invent outcome or service-level claims.
