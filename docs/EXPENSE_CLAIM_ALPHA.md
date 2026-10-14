# Synthetic expense claims in the internal alpha

**Status:** Software workflow for synthetic records only

The Expenses screen lets an assigned organization member create one draft per expense and submit it for review. Each claim is linked to a job. The current build has no receipt upload or accepted-evidence path. A claimant must explain why a receipt is missing; a different authorized reviewer must record a reasoned waiver before approval. Do not enter real expense details or files.

The [MVP workflow](EXPENSE_CLAIM_MVP_WORKFLOW.md) defines the product rules. [ADR-005](ADR-005-EXPENSE-EVIDENCE-HANDLING.md) gates receipt storage, scanning, access auditing, retention, deletion, and real-data use.

## Use the screen

1. Sign in to an organization and open **Expenses**. An active job assignment is required to create or submit a draft. A cancelled job cannot receive a new claim.
2. Enter the expense date, exact amount, three-letter uppercase currency, category, business purpose, and optional merchant. Enter a missing-receipt explanation before submitting. Drafts can be edited.
3. Submit the draft. An owner, admin, or operations member other than the claimant may return it with a reason, reject it with a reason, or waive the missing receipt with a reason and then approve it.
4. Edit a returned claim before resubmitting it as a new version. The prior submitted snapshot and review history remain visible. A waiver from an earlier version does not carry over.
5. The claimant may withdraw a draft, submitted, or returned claim. Approval, rejection, and withdrawal are terminal in this alpha.

Claimants retain their own claim history after job unassignment while they remain organization members. Reviewers can see organization claims. Finance members see approved claim metadata for other people, without reasons, history, or receipt access. A finance member who is also the claimant retains access to their own claim. Existing support grants do not provide claim access.

Approval does not create an invoice line, ledger entry, reimbursement, payroll item, or payment. Currencies stay separate.

## API contract

All routes require an authenticated session and organization membership. JSON writes require the session CSRF token.

| Route | Method | Purpose |
|---|---|---|
| `/api/organizations/{organization_id}/expense-claims/` | GET | List claims within the caller's role scope. |
| Same route | POST | Create a draft. Supply `job_id`, `expense_date`, `amount` as a decimal string, `currency`, `category`, `purpose`, and optional `merchant` and `missing_receipt_explanation`. |
| `/api/organizations/{organization_id}/expense-claims/{claim_id}/` | GET | Read a claim within the caller's role scope. |
| Same route | PATCH | Edit only a claimant-owned draft or returned claim. Supply changed claim fields and the current `revision`; job, organization, claimant, and receipt state cannot be changed. |
| `/api/organizations/{organization_id}/expense-claims/{claim_id}/transition/` | POST | Supply `action`, current `revision`, and `reason` where required. Actions: `submit`, `return`, `resubmit`, `waive`, `approve`, `reject`, `withdraw`. |

For example, a synthetic transition body is:

```json
{"action":"waive","revision":2,"reason":"Synthetic exception approved for workflow check"}
```

The API increments `revision` after each successful mutation. A stale revision returns HTTP 409; refresh the claim before retrying. The `version` field identifies the submitted claim snapshot and increments on resubmission. History records the actor, time, reason, status, version, and claim fields for each action. Client-supplied receipt or waiver flags are rejected. The server derives `receipt_state` as `missing` or `waived`; it cannot report accepted evidence in this increment.

The API returns 404 for claims outside the caller's organization or action scope, 400 for invalid fields, and 409 for a stale revision or invalid status transition.

## Implementation boundary

This increment creates no upload endpoint or storage adapter. Real receipt and expense data remain blocked until the controls and open decisions in ADR-005 are implemented and verified. The next software increment can add accepted evidence only with private storage, quarantine/scanning, access audits, retention and deletion, and tests covering those controls.
