# Employee leave requests

**Status:** Implemented for organization members; no leave entitlement or payroll calculations

The People area provides a basic request-and-decision workflow. Organization members can submit and track their own requests. Owners, admins, and operations members can review requests from other members in the same organization.

## Request and decision flow

- A request contains an inclusive start date, end date, category (annual, personal, parental, or other), and an optional short note.
- Requests cannot start in the past, have an end date before the start date, exceed 367 inclusive days, or overlap another pending or approved request for the same member.
- The requester can view their own requests and cancel a pending request.
- An organization manager can approve or reject another member's pending request. Rejection requires a short reason. A manager cannot review their own request.
- Each submission, decision, and cancellation records the actor, action, timestamp, and any reason. A decided or cancelled request cannot be changed or decided again.
- Employees can see their own request history. Managers can see organization requests and their histories. Other organization members cannot access another member's request.

## Privacy and product boundaries

Use the note only for brief context needed to review dates. Do not include medical details, identity documents, or other sensitive information. The workflow does not include attachments or medical records.

Categories are labels for organizing requests; the application does not calculate available leave, paid/unpaid entitlement, accrual, carryover, holidays, or statutory rules. It does not implement payroll, notifications, or calendar integrations. Businesses must apply their own policies outside this workflow until those capabilities are separately defined and implemented.

## API

All routes are scoped to an organization and require an authenticated organization membership.

| Route | Method | Use |
| --- | --- | --- |
| `/api/organizations/{organization_id}/leave-requests/` | `GET` | List the caller's requests, or organization requests for owner/admin/operations. Optional `?status=pending\|approved\|rejected\|cancelled`. |
| Same route | `POST` | Submit `start_date`, `end_date`, `category`, and optional `note`. Requester and organization are derived from the session. |
| `/api/organizations/{organization_id}/leave-requests/{id}/` | `GET` | Read a request within the caller's scope. |
| `/api/organizations/{organization_id}/leave-requests/{id}/transition/` | `POST` | Submit `action` (`approve`, `reject`, or `cancel`) and optional `reason`. |

The endpoint never accepts a caller-selected employee or membership ID. A foreign or unauthorized request is returned as not found. Rejection reasons are limited to 240 characters. The current workflow is an internal alpha capability and makes no claim about labor-law compliance.
