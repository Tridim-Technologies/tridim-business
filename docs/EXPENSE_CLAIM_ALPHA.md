# Synthetic expense claims in the internal alpha

**Status:** Software workflow for synthetic records only

The Expenses screen lets an assigned organization member create one draft per expense and submit it for review. Each claim is linked to a job. A gated local upload path can accept synthetic JPEG, PNG, and PDF evidence after server validation and a clean ClamAV scan. It is disabled by default and must never be used with real expense information or files. When disabled or unavailable, a claimant explains why the receipt is missing and a different authorized reviewer must record a reasoned waiver before approval.

The [MVP workflow](EXPENSE_CLAIM_MVP_WORKFLOW.md) defines the product rules. [ADR-005](ADR-005-EXPENSE-EVIDENCE-HANDLING.md) defines the safeguards; production storage/scanning, access-auditing review, retention, backup, deletion, and real-data use remain gated.

## Use the screen

1. Sign in to an organization and open **Expenses**. An active job assignment is required to create or submit a draft. A cancelled job cannot receive a new claim.
2. Enter the expense date, exact amount, three-letter uppercase currency, category, business purpose, and optional merchant. Attach a synthetic receipt if the development upload path is enabled, or enter a missing-receipt explanation before submitting. Drafts can be edited.
3. Submit the draft. An owner, admin, or operations member other than the claimant may return it with a reason, reject it with a reason, record a reasoned waiver when evidence is missing, or approve it when the current version has accepted evidence or a waiver.
4. Edit a returned claim before resubmitting it as a new version. The prior submitted snapshot and review history remain visible. A waiver from an earlier version does not carry over.
5. The claimant may withdraw a draft, submitted, or returned claim. Approval, rejection, and withdrawal are terminal in this alpha.

Claimants retain their own claim history after job unassignment while they remain organization members. Reviewers can see organization claims and evidence. Finance members see approved claim metadata for other people, without reasons, history, or evidence access. A finance member who is also the claimant retains access to their own claim and evidence. Existing support grants do not provide claim access.

## Local synthetic receipt evidence

The evidence route is available only when Django is running with `DEBUG=1` and `EXPENSE_EVIDENCE_ENABLED=1`. Keep it disabled for normal work. It uses a private local directory outside static/media serving, defaulting to `.private-evidence/` in the repository root, and a local ClamAV daemon exposed through a Unix socket. Set `EXPENSE_EVIDENCE_CLAMD_SOCKET` to that socket path. The application does not install or start ClamAV. If the scanner is not configured, times out, or returns an invalid result, the upload stays quarantined and cannot be downloaded.

Only use generated synthetic files. Current limits are 10 MiB per file, five files per claim version, and 25 MiB across a claim. The backend checks the extension, declared MIME type, file signature, image decoding/dimensions, PDF parsing/encryption/page count, and SHA-256 digest. Originals are stored under opaque names with directory mode `0700` and file mode `0600`; download requires a fresh organization/claim/role check and is sent as an attachment with `nosniff`. A draft claimant may remove evidence. Submitted evidence remains attached to its version; evidence added after return belongs to the next version.

The `cleanup_expense_evidence` command purges stale quarantined/rejected files and retries removal of deleted objects. It does not select a retention period or purge accepted evidence. Do not use this local adapter for production or real business data. Production parsing isolation, storage/scanner selection and security review, customer-specific retention and deletion, backups, support ownership, monitoring, and incident response remain open readiness gates.

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
| `/api/organizations/{organization_id}/expense-claims/{claim_id}/evidence/` | GET, POST | List evidence or upload a multipart `file` and current `revision`; upload requires the development gate and a clean scan. |
| `/api/organizations/{organization_id}/expense-claims/{claim_id}/evidence/{evidence_id}/` | GET, DELETE | Download accepted evidence as an attachment or remove it from an editable draft/returned version. |

For example, a synthetic transition body is:

```json
{"action":"waive","revision":2,"reason":"Synthetic exception approved for workflow check"}
```

The API increments `revision` after each successful claim mutation. A stale revision returns HTTP 409; refresh the claim before retrying. The `version` field identifies the submitted claim snapshot and increments on resubmission. History records the actor, time, reason, status, version, and claim fields for each action. Client-supplied receipt or waiver flags are rejected. The server derives `receipt_state` as `missing`, `accepted`, or `waived` for the current submitted version. The evidence list shows earlier versions as immutable history.

The API returns 404 for claims/evidence outside the caller's organization or action scope, 400 for invalid fields, and 409 for a stale revision or invalid status transition. Uploads use the same session cookie and CSRF token as other writes; the browser must send `multipart/form-data` without setting the `Content-Type` header manually.

## Implementation boundary

This gated synthetic increment adds an upload endpoint, local private storage, validation, quarantine/scanning, role checks, access audit events, safe downloads, and bounded cleanup. Real receipt and expense data remain blocked until the remaining controls and open decisions in ADR-005 are implemented and verified.
