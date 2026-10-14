# Expense claim MVP workflow

**Status:** Synthetic claim core implemented in issue #53; no real expense data is authorized

**Date:** 14 October 2026

**Scope:** Public core product, one expense per claim, linked to one job

This document fixes the claim shape and review rules used by the [synthetic alpha workflow](EXPENSE_CLAIM_ALPHA.md). [ADR-005](ADR-005-EXPENSE-EVIDENCE-HANDLING.md) governs receipt files and remains the gate for any actual upload or real-data use.

## Claim shape and validation

An MVP claim represents **one expense**, not a multi-line report. It belongs to one organization and one job. The server derives the organization and claimant from the authenticated context; callers cannot choose a different claimant or move a claim to another organization.

| Field | MVP rule |
|---|---|
| Claim ID, organization, job, claimant | Server-assigned IDs and relationships; the job must belong to the selected organization. |
| Expense date | Required calendar date, no future date. A late claim can refer to a past expense. |
| Amount and currency | Positive exact decimal amount, stored to five decimal places in line with the current internal finance model; three-letter uppercase currency code. Never use binary floating point or add unlike currencies. Currency-specific rounding and reimbursement conversion are later decisions. |
| Category | Required: travel, meals, materials, or other. `other` needs a useful description. The categories are a small starting list, not a tax classification. |
| Merchant and description | Merchant is optional; a short business-purpose description is required. Bound lengths and trim whitespace. |
| Receipt state | Server-derived from accepted evidence for the current claim version, or an explicit reviewer waiver. A client-supplied `has_receipt`, `accepted`, or `waived` flag has no authority. |
| Status, version, actors, timestamps | Server-controlled, with a versioned event history for submission, return, resubmission, waiver, approval, rejection, and withdrawal. |

The expense amount remains an operational claim. Approval does not post an accounting expense, reimburse the claimant, create an invoice line, or reduce a customer receivable. The claim currency need not match the job quotation currency; reports keep currencies separate unless a later approved FX policy exists.

## Roles and access

| Actor | Read | Write or decide |
|---|---|---|
| Current job assignee who is an organization member | Own claims on the job | Create and edit own draft; submit it while assigned to a job that is not cancelled. |
| Claimant after job unassignment | Own earlier claims while still an organization member | Withdraw a pending claim or correct a returned claim. Cannot create a new claim without a current assignment. |
| Owner, admin, operations | Organization claims and review history | Review claims submitted by another person: return, approve, reject, or waive missing evidence with a reason. May submit their own claims only when assigned; cannot review or waive their own claims. |
| Finance | Approved claim metadata needed for later finance work, scoped to the organization | No claim approval, evidence access, or expense posting in the MVP. A broader finance view requires a separately defined purpose and permission. |
| Sales or other member | Own claims only if assigned | Same claimant actions as another assignee; no manager review. |
| Tridim support | No default access | Existing delivery or finance support scopes do not grant expense-claim or receipt access. A separate purpose-bearing, time-limited and audited scope would need a new decision and implementation. |

Every read and action checks current organization membership and the claim's organization and job. Identifiers from another organization return no claim data. A claimant retains access to their own submitted history after unassignment so a manager can ask for corrections; loss of organization membership ends normal access. Reviewers cannot alter the claimant's amount, date, category, merchant, or description directly.

## Status and decision flow

| From | Action and actor | To | Required conditions and record |
|---|---|---|---|
| New | Create by current assignee | Draft | Job is in the organization and is not cancelled. |
| Draft | Edit by claimant | Draft | Only claimant fields change; record update time. |
| Draft | Submit by claimant | Submitted | Assignee is current, job is not cancelled, fields validate, and either accepted receipt evidence exists or the claimant gives a missing-receipt explanation. Snapshot the submitted version. |
| Draft | Withdraw by claimant | Withdrawn | Record actor and time; draft may be removed from normal lists but not used to erase a submitted history. |
| Submitted | Return for correction by a reviewer | Returned | Reviewer is not claimant; reason required. |
| Returned | Edit and resubmit by claimant | Submitted | Still an organization member; validate all fields and evidence rules again. Increment claim version and preserve the prior snapshot and decision. A previous waiver does not carry over. |
| Submitted | Waive missing receipt by a reviewer | Submitted | Reviewer is not claimant; reason required. Waiver is bound to this claim version, remains in history, and does not fabricate an attachment. |
| Submitted | Approve by a reviewer | Approved | Reviewer is not claimant; current version has accepted evidence or a valid waiver. Record actor, time, and the reviewed version. |
| Submitted | Reject by a reviewer | Rejected | Reviewer is not claimant; reason required. This is a final decision. |
| Submitted or returned | Withdraw by claimant | Withdrawn | Pending claim only; record actor, time, and the latest submitted version. |

Approved, rejected, and withdrawn claims are terminal in this MVP. A later correction to an approved claim needs a separate controlled adjustment process; it must not overwrite the approved record. A rejected claim cannot be silently resubmitted as the same claim. If a corrected new claim is allowed later, link it to the rejected claim and flag possible duplicates for review.

An organization must have someone other than the claimant with review permission. If none is available, the claim remains pending; self-approval is not an exception path. Job cancellation or reassignment after submission does not silently discard an expense already incurred. The reviewer makes an explicit decision with the event history visible.

## Receipt requirement and implementation gate

The public MVP starts with **a receipt required for each submitted claim**, with a narrow missing-receipt exception. The claimant must either attach an accepted receipt for the current version or state why it is missing. A reviewer can waive it only through the explicit action above. The interface should show missing evidence before submission and make the reviewer decision clear. Category- or amount-based rules, a reusable receipt inbox, OCR, and automated extraction are later candidates.

Receipt acceptance is a server-side result of the private upload, quarantine, validation, and scanning flow in ADR-005. The claim workflow may be built with synthetic records before that flow exists, but ordinary receipt-based approval must stay unavailable until it does. A synthetic-only build can exercise the explicit missing-receipt/waiver path; it must not offer a fake `receipt_present` switch or treat every claim as waived. Real files and real claims remain blocked until storage, scanning, access auditing, retention, and deletion controls are verified.

## Consistency and audit rules

- Perform submission, review, waiver, resubmission, and withdrawal as atomic server-side transitions. Lock the claim/version during a decision so concurrent reviewers or a claimant withdrawal cannot produce two final outcomes.
- Record previous and new status, actor, time, claim version, reason where required, and the fields/evidence IDs reviewed. Keep actual receipt bytes and extracted text out of history events and logs.
- Recheck current membership and the relevant role/assignment at action time. Do not rely on hidden buttons for authorization.
- Keep list and detail responses scoped: claimants see their own claims, reviewers see organization claims, and finance sees approved metadata only. Exports follow those same boundaries.
- Never total claims from different currencies together. Approval alone has no ledger, payable, payroll, or reimbursement side effect.

## Synthetic acceptance scenarios for the implementation issue

1. An assigned member creates a draft, edits it, and submits it with valid exact amount, currency, category, purpose, and a missing-receipt explanation.
2. Unassigned members and cross-organization identifiers cannot create, list, view, change, or review another claim.
3. A reviewer returns a claim with a reason; the claimant resubmits a corrected version and the prior snapshot remains visible. A waiver on the old version cannot authorize the new one.
4. A reviewer cannot decide their own claim. A second authorized reviewer waives the missing receipt with a reason and then approves that version.
5. Approval is refused when current evidence is missing and no current-version waiver exists. Rejection and withdrawal preserve the event history and prevent further editing.
6. Future dates, zero/negative or over-precision amounts, malformed currency codes, empty purpose, and invalid category are rejected.
7. A claim submitted before job cancellation or unassignment remains reviewable; a new claim on a cancelled job is blocked.
8. Concurrent review or withdrawal attempts cannot produce two terminal outcomes. Finance receives only approved metadata, and no action posts to invoice, ledger, or reimbursement records.

## Next implementation boundary

Build claim records, versioned status history, tenant and role checks, and a small UI with synthetic data. The first increment can use the explicit missing-receipt and reviewer-waiver path. Receipt upload/storage/scanning is a separate follow-up that must pass ADR-005. Do not introduce real business data or deployment decisions as part of the claim-workflow increment.
