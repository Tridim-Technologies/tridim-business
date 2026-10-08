# Django Admin Support Access

This procedure applies to the open-source Tridim Business Platform. It grants narrowly scoped, read-only access for support investigations. It does not grant access to the Enterprise product.

## Grant access

1. A platform superuser creates or selects an active staff account in Django Admin. Set `is_staff` and leave `is_superuser` off. Tenant users should not be given staff access.
2. In **Support access grants**, create a grant for the staff account and one organization. Select the smallest relevant data scope, enter the support purpose, and set an expiry no more than eight hours after grant time.
3. Django records the granting superuser and grant time. The grant form rejects an empty purpose, inactive/non-staff accounts, and an expiry outside the eight-hour window.

Each grant covers one organization and one data scope:

| Scope | Admin data available |
|---|---|
| Customer records | Customer directory |
| Quotations | Quotations and their lines/history |
| Jobs and delivery history | Jobs, assignments, notes, and status/due-date history |
| Invoices and sequences | Invoices and invoice numbering sequences |
| Daraja payment diagnostics | Linked sandbox payment attempts and callbacks |

Support staff can view scoped records only. They cannot create, edit, delete, or use bulk actions. Related quotation and invoice lines/history are displayed read-only under their already-scoped parent record. Organization and membership records, user and group administration, and support grant management remain superuser-only. Unmatched Daraja callbacks without a tenant-linked attempt are not exposed; the payment diagnostics view hides phone numbers and the raw provider response.

## Revoke and audit

- Revoke access immediately using the **Revoke selected support access** action in the grants list. The revocation timestamp is retained; grants cannot be deleted.
- Expired or revoked grants stop authorizing requests without requiring logout. Disable or remove staff status from the account when support work is complete.
- The support access audit events screen records each scoped list and record view with its timestamp, grant, model, and record identifier. Grant creation and revocation are also recorded in Django's admin history.
- Audit events are read-only and cannot be deleted through Django Admin.

Platform superusers have the normal global Django Admin privileges and bypass support grants. Reserve those accounts for trusted platform operators; the support-view audit stream does not record superuser reads.

## Apply the database migration

From `backend/`, run:

```sh
uv run python manage.py migrate
```
