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
3. Create the invitation. If optional email is enabled and the mail backend accepts the message, the app submits the link and does not return the raw token to the manager. Backend acceptance does not confirm inbox delivery.
4. If delivery is disabled or unavailable, copy the one-time link shown in the app and share it directly with the intended recipient.

The link is a secret credential. Anyone who receives it can attempt to accept the invitation, so share it through a suitable private channel. It works once and expires seven days after creation. Managers cannot recover the token from the invitation list; revoke it and create another invitation if the link is lost or exposed.

Outbound delivery uses Django's configured SMTP backend. It is disabled by default; see [`backend/.env.example`](../backend/.env.example) for settings and provide them to the backend process through its environment. Django does not load `.env` files automatically. If the mail backend rejects the message, the pending invitation remains usable and the manager receives the one-time manual link. A successful SMTP handoff does not confirm that the message reached an inbox. The app does not store or display the raw token after successful handoff.

If the SMTP server accepts a message but the recipient cannot find it, revoke that invitation and create a replacement. The manager can share the replacement's one-time link if email submission is unavailable.

Email delivery does not verify ownership of the email address. Existing accounts must sign in with an address that matches the invitation, but this is not mailbox verification. Do not treat an address as verified solely because an invitation was emailed or accepted.

## Accept an invitation

- A person without an account can choose a username and password. Django's configured password validators apply, and the account email is set to the invited address.
- A person with an existing account signs in with that account. Its email must match the invitation address. Existing passwords are not changed.
- Successful acceptance adds the invited membership and opens the invited organization in the app.
- Expired, revoked, malformed, or already-used links cannot create a membership. Acceptance and membership creation happen in one database transaction.

## API routes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET`, `POST` | `/api/organizations/{organization_id}/invitations/` | List recent invitations or create a role-bounded invitation. A successful email send returns `email_sent: true` and no token; otherwise the create response includes the one-time fallback token. |
| `POST` | `/api/organizations/{organization_id}/invitations/{invitation_id}/revoke/` | Revoke a pending invitation. |
| `POST` | `/api/invitations/inspect/` | Inspect invitation details using a token in the JSON body. |
| `POST` | `/api/invitations/accept/` | Accept with a signed-in matching account or create an account from the invitation. |

The API stores a SHA-256 digest of the high-entropy token, not the raw token. Invitation URLs place the token in the browser fragment; the fragment is supplied in the acceptance request body and is not part of the initial HTTP request URL. Email sending does not add mailbox verification. No enterprise-only provisioning, bulk import, account recovery, or provider-specific email integration is included.
