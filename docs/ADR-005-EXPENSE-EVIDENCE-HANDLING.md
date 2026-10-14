# ADR-005: Private expense evidence handling and lifecycle

**Status:** Accepted as a provider-neutral product and security design; implementation is gated on the open decisions below

**Date:** 14 October 2026

**Decision owner:** Founder

## Context

The MVP includes employee expense claims, but currently has no expense-claim or file-upload implementation. Receipts can contain names, addresses, payment details, travel patterns, and unrelated personal information. A receipt must remain attached to the right organization and claim, available only to authorized people, and governed by a lifecycle that works across storage, backups, exports, and deletion.

The product draws capability ideas from business suites such as Microsoft Dynamics 365, SAP Concur, Oracle Fusion Cloud, and other ERP/expense products. Their public guidance illustrates useful patterns: mobile capture and upload, reusable receipt inboxes, evidence at expense-line or report level, policy-based receipt requirements, and a review/audit path for missing evidence. The design here uses those patterns as a benchmark, not as a specification to copy. Tridim Business should aim to make the common path simpler, keep evidence portable, make privacy controls understandable, and avoid adding automation or configuration that customers do not need. Whether this is better must be established through product evaluation.

## Decision

1. **Treat evidence as private tenant data.** An evidence object belongs to one organization and one expense claim. Every upload, list, preview, download, export, replace, and delete request must authorize the current actor against both the organization and claim. Never infer authorization from a file ID or object key.
2. **Keep file bytes out of PostgreSQL and public web roots.** Store claim metadata and an opaque storage reference in the relational database. Put bytes in a private object-storage adapter behind an application-owned interface. Do not select or provision a provider in this ADR. Local development may use a private, ignored directory outside static/media serving, with synthetic files only; it is not a production storage option.
3. **Use a narrow initial file policy.** Initially accept JPEG, PNG, and PDF only. Reject SVG, HTML, Office files, archives, executables, encrypted/password-protected PDFs, malformed files, and files whose inspected content does not match the declared type. Suggested initial limits are 10 MiB per file, 5 files per claim, and 25 MiB total per claim. Keep these limits configurable and revisit them using real workflow needs before any real-data evaluation.
4. **Validate and quarantine before evidence is usable.** Enforce request and streaming size limits; verify extension, declared MIME type, file signature, and successful decoding/parsing on the server. Check image dimensions and PDF page count against bounded limits to avoid resource exhaustion. Place new files in a private quarantine state and scan them for malware before attachment or preview. Scanner or parser errors fail closed. Files that fail validation or scanning are not downloadable and are removed through a bounded cleanup process. Do not execute, render, or fetch active content from an uploaded file.
5. **Protect original evidence and serve safely.** Preserve the accepted upload as immutable submitted bytes, record a SHA-256 digest and detected media type, and do not silently rewrite the original. Do not extract EXIF or other incidental metadata into searchable fields. If previews are offered, generate a separate derivative with metadata removed; never use that derivative as the source evidence. Require authorization on every preview/download. Serve originals as attachments with a server-selected filename, safe content type, `X-Content-Type-Options: nosniff`, and no public or guessable URL. A future storage adapter may use a narrowly scoped, short-lived download URL only if the application can audit issuance and expiry; it must not become a durable share link.
6. **Make evidence changes append-only after submission.** A draft claimant may remove or replace an attachment. Submission locks that claim version. After return for correction, a claimant may add a new evidence version or replacement; the old version and decision history remain linked and cannot be overwritten. An approved claim's evidence is immutable except for a separately audited privileged correction or legal process. Rejection, request-for-information, or receipt-waiver decisions require an actor, timestamp, and reason. A waiver records that evidence was waived; it does not delete an existing file.
7. **Keep access role- and purpose-limited.** The claimant can manage their own draft and view their submitted claims. Authorized organization expense reviewers can review claims and evidence. Finance access should be limited to the financial tasks the organization assigns; it does not grant blanket access to all evidence. Tridim support has no default access. Any exceptional support view uses the existing purpose-bearing, time-limited, audited support grant mechanism. Exports and bulk downloads require the same tenant and role checks as individual access.
8. **Audit actions without copying evidence into logs.** Record organization, claim, evidence ID, actor, action, timestamp, outcome, and a bounded reason for upload, scan result, preview/download, replacement, export, deletion, retention hold, and support access. Do not log file bytes, raw OCR text, sensitive receipt fields, signed URLs, or credentials. Restrict audit access and apply a documented retention schedule to audit records.
9. **Use encryption and lifecycle controls at the storage boundary.** Require TLS in transit and encryption at rest provided by the eventual storage service. Keep tenant/object keys opaque and server-generated. Limit storage identity permissions to the operations the application needs; separate any scanning identity where practical. The chosen service must support private access, access auditing, lifecycle/deletion controls, and a recovery model before real evidence is accepted.
10. **Make retention explicit before real-data use.** Do not invent one global retention period or claim legal compliance. Before an organization uploads real evidence, define its applicable retention schedule with the customer and qualified local accounting/privacy advice, including any statutory minimum, contractual rule, and business purpose. Apply a legal hold only through an explicit, authorized, reviewed, and audited process. At expiry, purge the original and derivatives idempotently and retain only the minimum non-content tombstone needed to explain deletion, subject to the agreed recordkeeping rule. Do not leave evidence indefinitely because cleanup failed; report and retry failures.
11. **Treat backups and exports as additional copies.** Document encryption, access, retention, restore, and deletion behavior for file backups separately from database backups. A restore must reconcile expired/deleted evidence before users can access restored records. An authorized export may include originals and a manifest with claim/evidence IDs, hashes, media types, and timestamps; record who exported it and when. Do not email evidence as an attachment. Create temporary export bundles in private storage with a short expiry and automatic purge.
12. **Do not send evidence to AI or other processors by default.** OCR, duplicate detection, receipt extraction, or third-party processing are later opt-in capabilities. Before enabling one, disclose the processor and purpose, limit fields sent, define processor retention/training behavior, get organization authorization, and provide a manual path. Any extracted values are suggestions for the employee to verify, never authoritative financial data.

## Recommended product shape

| Benchmark capability | Product response |
|---|---|
| Mobile camera/file capture and receipt association | Make direct capture or a simple file picker the common path; keep the initial workflow attached to the individual expense claim so evidence has a clear owner. Add an unattached receipt inbox only if discovery shows it solves a real workflow problem. |
| Receipt rules and missing-evidence holds | Start with a small, understandable rule per organization and expense category. Explain missing evidence before submission. Allow only an authorized reviewer to waive a requirement, with a reason and audit history. Add amount thresholds and more complex policies only after validation. |
| Review, request-more-information, correction, and audit | Keep claim status and evidence version history together; return a claim with a clear reason and let the submitter add a new version without erasing what was reviewed. |
| OCR or automated extraction | Defer by default. If later introduced, require explicit opt-in, show extracted fields for confirmation, and never make an unreviewed extraction alter approved financial records. |
| Large configurable ERP attachment systems | Prefer private-by-default storage, visible retention state, portable exports, and a few coherent controls over exposing infrastructure settings to each business. |

This is an initial public-core product direction. Advanced configurable policies, automated audit selection, OCR, and integrations remain candidates for separate validation and may belong in the enterprise edition only after the public/enterprise boundary is deliberately documented.

## Threats and required controls

| Threat | Required control |
|---|---|
| Cross-tenant object access or guessed IDs | Bind storage metadata to organization and claim server-side; authorize every operation; use random opaque keys; test cross-tenant list, preview, download, replacement, export, and deletion. |
| Malware, active content, or parser exploit | Allowlist formats; inspect signatures and parse in a bounded, isolated process; quarantine and scan; fail closed; never serve untrusted content inline. |
| Oversized file, decompression bomb, or image/PDF resource exhaustion | Enforce streaming byte, dimensions, page-count, and time limits before processing; reject archives and unsupported compound formats. |
| Public bucket, leaked URL, or storage credential misuse | Private storage only; no permanent links; use least-privilege identities; audit access; expire temporary access quickly; rotate/revoke compromised credentials. |
| Receipt contains excess personal data or location metadata | Tell users to upload only relevant evidence; avoid collecting unrelated identity/health data; do not index EXIF/OCR text; remove metadata from previews; restrict original access. |
| Silent replacement or deletion hides an approval decision | Lock submitted versions; create append-only replacement/history records; require reasoned, audited privileged corrections; keep waiver distinct from deletion. |
| Retention cleanup or backup restore resurrects deleted evidence | Idempotent purge with observable failure handling; maintain deletion tombstones; reconcile restored databases and objects before access; set backup expiry consistently with approved retention. |
| Export or support access creates an uncontrolled copy | Reuse tenant/role policy; audit exports and support views; use private short-lived bundles; no email attachment delivery; enforce purpose and expiry for support grants. |
| Unapproved OCR or external processing | No third-party processing by default; require explicit organization opt-in and documented processor purpose, retention, training use, access, and deletion terms. |

## Consequences

- Separating file content from business records improves storage portability and avoids large database rows, but requires a reliable relationship between database metadata, object storage, scanning, backups, and deletion.
- Quarantine and scanning add implementation and operating work. If a safe scanner/storage adapter is unavailable, uploads must remain disabled rather than bypassing those checks.
- Preserving immutable submitted versions improves reviewability but uses more storage and makes retention policy and deletion execution essential.
- Per-organization evidence requirements can fit different workflows, but the initial version should expose only a small number of understandable policy choices.
- The exact privacy, tax, accounting, and record-retention obligations differ by jurisdiction and customer. This ADR is a technical/product design, not legal advice or a compliance certification.

## Open decisions before implementation or real-data use

- Confirm whether the initial workflow is one claim per expense or whether employees need multi-line reports; keep each file attached to an unambiguous claim or line.
- Confirm initial receipt-required behavior, reviewer roles, and whether finance needs evidence access beyond an assigned review task.
- Select the file scanner, supported isolation boundary, private storage provider/adapter, encryption and key ownership, storage regions, and monitoring owner.
- Obtain customer/accounting/privacy advice for each deployment's retention period, legal holds, export obligations, and deletion from backups.
- Verify exact file limits against expected mobile capture conditions and accessibility needs.
- Agree on support escalation and breach-response steps specifically for evidence objects.
- Review data-processing terms before enabling OCR, document preview services, email ingestion, or another external processor.

No cloud service, storage bucket, scanner, retention duration, expense claim implementation, or real-data evaluation is authorized by this ADR. Deployment remains deferred.

## Benchmark references

Official product documentation reviewed 14 October 2026. These pages support capability observations only; product availability and behavior may change.

- Microsoft Dynamics 365 Project Operations, [Manage expenses with the mobile app](https://learn.microsoft.com/en-us/dynamics365/project-operations/expense/mobile-app-manage-expenses) — camera, device upload, receipt association/change/detach, and unattached receipt behavior.
- Microsoft Dynamics 365 Finance, [Configure document management](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/organization-administration/configure-document-management) — attachment storage locations, file-type controls, virus scanning, attachment history, export, and recovery topics.
- Microsoft Dynamics 365 Project Operations, [Define expense policies](https://learn.microsoft.com/en-us/dynamics365/project-operations/expense/set-up-policies) — date-effective expense rules and error/justification outcomes.
- SAP Concur, [Upload a receipt image](https://help.sap.com/docs/CONCUR_EXPENSE/f45ee181c99e4d93afbab48a5b75ea50/e90d98bc90cd4b1e9e86b904f7d1f649.html) and [receipt image overview](https://help.sap.com/docs/CONCUR_EXPENSE/cd24ad794821491e8f65f76f61dffcc6/e319217953c0454faa1c3d1b2daa5812.html) — receipt libraries, report/expense attachment levels, accepted formats, and company receipt policies.
- SAP Concur, [Hold for Receipt Image](https://help.sap.com/docs/CONCUR_EXPENSE/bb83754b1c5541808d50c09901e11475/a31bcde9e8fb40c582bc67f480986452.html) — optional workflow hold until required receipt images are attached.
- Oracle Fusion Cloud Financials, [Options for setting up receipt management rules](https://docs.oracle.com/en/cloud/saas/financials/26b/faiex/options-for-setting-up-receipt-management-rules.html) and [expense report approval](https://docs.oracle.com/en/cloud/saas/financials/26b/fawde/expense-report-approval.html) — receipt rules at organization/template/expense-type levels and configurable approval routing.
- Oracle Fusion Cloud Financials, [Audit Actions](https://docs.oracle.com/en/cloud/saas/financials/26b/fawde/audit-actions.html) — audit outcomes including reject, request more information, waive receipts, and release hold.
