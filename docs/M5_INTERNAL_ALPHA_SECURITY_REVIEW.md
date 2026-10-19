# M5 Internal Alpha Readiness Review

**Status:** Documentation and local synthetic readiness review completed; local deletion journal/replay implemented; production and hosted gates remain open
**Reviewed:** Baseline review 15 October 2026; deletion-ledger design update 19 October 2026
**Scope:** Tenant and role boundaries, support access, endpoint abuse controls, synthetic expense evidence, database recovery, monitoring, incident ownership, and sensitive logging.

This review reconciles current implementation notes, existing regression coverage, and the local synthetic workflows. It is not an independent penetration test, legal review, production security certification, or hosted-operations rehearsal.

## Readiness summary

| Area | Current status | Evidence and limitation |
|---|---|---|
| Tenant and role boundaries | **Implemented and covered by local regression tests** | Organization-scoped APIs and finance exports enforce role checks; see [issue #36](https://github.com/Tridim-Technologies/tridim-business/issues/36). No independent penetration test has been performed. |
| Scoped Django Admin support and privileged reads | **Implemented and covered by local regression tests** | Non-superuser staff access requires a time-limited, purpose-bearing organization/data-scope grant; successful list/detail reads are audited. Successful tenant-model list/detail reads by platform superusers are recorded separately with actor and, for object reads, organization. Global list reads have no single organization. This does not audit every admin model or direct database access; see [Admin Support Access](ADMIN_SUPPORT_ACCESS.md), [issue #37](https://github.com/Tridim-Technologies/tridim-business/issues/37), and [issue #69](https://github.com/Tridim-Technologies/tridim-business/issues/69). |
| Login/callback abuse controls | **Implemented; required operations are not scheduled/configured** | Shared database counters, bounded payloads, and short-lived unmatched callback retention are implemented. `cleanup_abuse_records` must be scheduled at least every five minutes. Proxy address handling is only meaningful when a future trusted proxy sets `REMOTE_ADDR` correctly; see [Endpoint Abuse Controls](ENDPOINT_ABUSE_CONTROLS.md) and [issue #38](https://github.com/Tridim-Technologies/tridim-business/issues/38). |
| Expense evidence | **Local synthetic deletion journal and replay implemented; production ledger remains open** | Development-only upload, validation, quarantine, ClamAV scanning, private local storage, scoped access, cleanup, pending deletion state, and a separate local SQLite journal/replay command are covered with generated files. The local journal can be rolled back or lost with local files and has no independent backup or storage-specific version reconciliation. Real evidence remains unsupported. See [ADR-005](ADR-005-EXPENSE-EVIDENCE-HANDLING.md#independent-deletion-ledger-design), [issue #97](https://github.com/Tridim-Technologies/tridim-business/issues/97), and [issue #99](https://github.com/Tridim-Technologies/tridim-business/issues/99). |
| Database recovery | **Local synthetic rehearsal passed; hosted recovery unverified** | PostgreSQL 16 logical backup/restore rehearsal passed locally on 15 October 2026. The chosen internal-alpha planning baseline is RPO up to 24 hours, RTO by the next business day, and a seven-day recovery window; these are not customer commitments and have not been configured or measured in a hosted environment. See [Database Backup and Restore](DATABASE_BACKUP_AND_RESTORE.md) and [issue #65](https://github.com/Tridim-Technologies/tridim-business/issues/65). |
| Monitoring and incident response | **Guidance documented; operations are not configured** | Cloud Monitoring and Cloud Logging are the preferred future direction, but there is no configured project, telemetry retention, or alert destination. No response-time commitment is defined. See [Monitoring and Incident Response](MONITORING_AND_INCIDENT_RESPONSE.md). |

### Readiness boundary

The verified evidence supports continued **local synthetic development**. It does not authorize real business data, real expense evidence, customer field evaluation, or hosted deployment. The local journal/replay implementation improves synthetic restore rehearsals only; an independently protected production ledger, storage-specific purge guarantees, and a hosted restore rehearsal remain open. Before any real-data evaluation, the project still needs a tested alert/incident path; scheduled cleanup and correct proxy behavior in the selected environment; production evidence storage/scanning isolation and customer-specific retention/deletion; backup reconciliation for evidence objects; and a scoped, approved evaluation and data-exit plan. Do not treat the planning RPO/RTO/window as service guarantees.

The alert destination, region, project, budget, and hosted operations remain unconfigured and outside this local documentation review.

## Review results

| Area | Result |
|---|---|
| Session and organizations | Session endpoints return the authenticated user and that user's organizations. Login POST is protected by Django CSRF middleware; regression tests cover CSRF behavior. |
| Tenant boundaries | Customer, quotation, job, invoice, payment, allocation, and export queries are scoped to the organization in the route. Cross-organization probing is denied or returns not found. |
| Customer directory roles | Owner, admin, sales, operations, and finance may read the tenant directory; employee directory access is denied. The prior employee read access was closed under issue #36. |
| Quotation roles | Owner, admin, sales, and operations may read quotations. Sales/owner/admin create or revise; owner/admin/operations accept work. The prior finance and employee read access was closed under issue #36. |
| Job roles | Employees see only currently assigned jobs and may add notes only to those jobs. Job managers control delivery updates and assignments; finance may read but not change delivery status. |
| Invoices and payments | Owner, admin, and finance roles are required. Object lookups for issue, void, record, allocation, and reversal operations are tenant-scoped. Tests cover role and tenant denial. |
| Finance exports | Exports use the same owner/admin/finance membership gate and organization-scoped querysets. CSV text beginning with formula characters is escaped; responses are private/no-store and carry an as-of timestamp. Tests cover roles, tenant scope, and CSV escaping. |
| Daraja callbacks | The callback is intentionally public and CSRF-exempt. Only a minimized summary is persisted; the phone number is hashed. A callback alone cannot confirm payment: the app queries Daraja and checks correlation before changing attempt status. Payloads and request rates are bounded; unmatched callback rows have a short retention and cleanup command. See [public endpoint abuse controls](ENDPOINT_ABUSE_CONTROLS.md). |
| Sensitive logging | No application logging or print calls were found in backend code. Provider tokens are not stored in attempt response data, and callback phone numbers are not stored in raw form. |
| Django Admin support access | Non-superuser staff need an active grant for one organization and one data scope; grants require a purpose and expire within eight hours. Admin list/detail reads are audited, and support views are read-only. |

## Follow-up risks

- Django Admin support grants are managed by platform superusers. They retain global privileges. The new platform-admin read audit records successful list/detail reads only for models using the support-scoped admin; it does not cover every Django Admin model or direct database access. Protect superuser accounts and review the audit log as platform operator data.
- Login and Daraja callback endpoints have database-shared abuse controls. Schedule `cleanup_abuse_records` at least every five minutes and configure proxy client-IP handling; these operational steps are required for the documented retention and per-client limits to work as intended.
- Before deployment, set `DJANGO_DEBUG=0`, provide a stable `DJANGO_SECRET_KEY`, and configure production host/CSRF settings. The development defaults are not production settings.

## Validation evidence

The repository test suite already covered cross-tenant customer, quotation, job, invoice, payment, and export behavior, plus finance export restrictions and CSV formula escaping. API and export coverage was expanded under issue #36; Django Admin tenant grants, scope restrictions, expiry, read-only access, and audit events are covered under issue #37. Validation is reported with the issue #37 pull request.
