# Organization invitations

This guide describes the current internal-alpha invitation flow. An invitation adds one account to one organization; it does not create an organization or grant access to any other organization.

## Who can invite

- Owners can invite members as admin, sales, operations, finance, or employee.
- Admins can invite sales, operations, finance, or employee members.
- Only an existing owner can grant admin. Invitations cannot grant owner access.
- Owners and admins can review recent invitations and revoke a pending invitation.

## Create and share an invitation

1. Sign in and select the organization.
2. Open **Invitations**, enter the intended email address, and choose an allowed role.
3. Create the invitation and copy the link shown once.
4. Share the link directly with the intended recipient. The app does not send email.

The link is a secret credential. Anyone who receives it can attempt to accept the invitation, so share it through a suitable private channel. It works once and expires seven days after creation. Managers cannot recover the token from the invitation list; revoke it and create another invitation if the link is lost or exposed.

Acceptance does not verify ownership of the email address. The application currently has no configured email sender or mailbox verification flow. Do not treat the address as verified solely because an invitation was accepted.

## Accept an invitation

- A person without an account can choose a username and password. Django's configured password validators apply, and the account email is set to the invited address.
- A person with an existing account signs in with that account. Its email must match the invitation address. Existing passwords are not changed.
- Successful acceptance adds the invited membership and opens the invited organization in the app.
- Expired, revoked, malformed, or already-used links cannot create a membership. Acceptance and membership creation happen in one database transaction.

## API routes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET`, `POST` | `/api/organizations/{organization_id}/invitations/` | List recent invitations or create a role-bounded invitation. The create response includes the raw token once. |
| `POST` | `/api/organizations/{organization_id}/invitations/{invitation_id}/revoke/` | Revoke a pending invitation. |
| `POST` | `/api/invitations/inspect/` | Inspect invitation details using a token in the JSON body. |
| `POST` | `/api/invitations/accept/` | Accept with a signed-in matching account or create an account from the invitation. |

The API stores a SHA-256 digest of the high-entropy token, not the raw token. Invitation URLs place the token in the browser fragment; the fragment is supplied in the acceptance request body and is not part of the initial HTTP request URL. No enterprise-only provisioning, bulk import, account recovery, or email integration is included.
