# M5 Internal Alpha Security Review — API and exports

**Status:** Scoped code review completed; review findings fixed or tracked below
**Reviewed:** 8 October 2026
**Scope:** Session and organization APIs, customer and quotation APIs, job APIs, invoice/payment APIs, finance CSV exports, and sensitive logging.

This is an implementation review with regression tests, not an independent penetration test or production security certification.

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

- Django Admin support grants are managed by platform superusers. Superusers bypass tenant grants and their reads are not recorded by the support-view audit stream; protect those accounts as platform operator credentials.
- Login and Daraja callback endpoints have database-shared abuse controls. Schedule `cleanup_abuse_records` at least every five minutes and configure proxy client-IP handling; these operational steps are required for the documented retention and per-client limits to work as intended.
- Before deployment, set `DJANGO_DEBUG=0`, provide a stable `DJANGO_SECRET_KEY`, and configure production host/CSRF settings. The development defaults are not production settings.

## Validation evidence

The repository test suite already covered cross-tenant customer, quotation, job, invoice, payment, and export behavior, plus finance export restrictions and CSV formula escaping. API and export coverage was expanded under issue #36; Django Admin tenant grants, scope restrictions, expiry, read-only access, and audit events are covered under issue #37. Validation is reported with the issue #37 pull request.
