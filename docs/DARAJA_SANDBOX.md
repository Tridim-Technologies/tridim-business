# Daraja sandbox invoice payment attempts

The first connector uses Safaricom Daraja **M-Pesa Express (STK Push)** for
prompt initiation and the matching **M-Pesa Express query** with
`CheckoutRequestID` for status checks. The general Daraja Transaction Status
API is a separate capability and is not used for STK checkout verification.

This is a sandbox integration only. Use synthetic organizations, customers,
phone numbers, invoices, and Daraja sandbox credentials. The app rejects a
non-sandbox `DARAJA_ENV`; there is no live payment configuration in this
release.

## Configuration

Provide the following settings through the local process environment or the
deployment secret manager. Do not commit them to the repository or include
them in logs.

| Setting | Purpose |
|---|---|
| `DARAJA_ENV` | Must be `sandbox`; defaults to `sandbox`. |
| `DARAJA_CONSUMER_KEY` | Consumer key for the sandbox Daraja app. |
| `DARAJA_CONSUMER_SECRET` | Consumer secret for the sandbox Daraja app. |
| `DARAJA_SHORTCODE` | Sandbox business shortcode. |
| `DARAJA_PASSKEY` | Sandbox M-Pesa Express passkey. |
| `DARAJA_CALLBACK_URL` | Public HTTPS URL ending at `/api/payments/daraja/sandbox/stk/callback/`. |

The connector stays unavailable until all credentials and the HTTPS callback
URL are configured.

## API flow

1. An authenticated owner, admin, or finance member sends a `POST` to
   `/api/organizations/{organization_id}/invoices/{invoice_id}/daraja/sandbox-attempts/`
   with a UUID `Idempotency-Key` header and JSON `amount` and `phone_number`.
2. The app accepts only an issued KES invoice and a positive whole-KES amount
   within its available balance. Pending or unresolved attempts reserve their
   amount so a retry cannot start a duplicate prompt.
3. The response contains the local attempt ID and Daraja checkout request ID.
   Poll its organization-scoped resource at
   `/api/organizations/{organization_id}/daraja/sandbox-attempts/{attempt_id}/`.
4. Daraja posts an asynchronous callback to the configured URL. The app stores
   a minimized callback summary with a hash of the payer number, deduplicates
   by `CheckoutRequestID`, and queries M-Pesa Express using that ID. A callback
   alone never marks a payment successful.
5. The app requires the query response to echo the stored checkout and
   merchant request IDs. For success it also checks the callback result,
   amount, and phone against the immutable attempt. Mismatches and uncertain
   responses remain in `review`; they do not create a ledger receipt.
6. A confirmed provider success is visible on the attempt. Finance records the
   receipt through the existing payment workflow using the checkout request ID
   as its reference, then explicitly allocates that receipt to the invoice.
   This release does not automatically create or allocate a `Payment` from a
   provider callback.

Finance can retry status verification for an attempt with a stored callback
using `POST` on
`/api/organizations/{organization_id}/daraja/sandbox-attempts/{attempt_id}/reconcile/`.
The endpoint requires the same organization finance authorization as other
payment operations. An attempt without a checkout ID or callback cannot be
retried automatically; review it before doing anything else.

## Safety boundary

- The published SDK calls the STK operations
  `lipa_na_mpesa_online_payment` and `lipa_na_mpesa_online_query`; the pinned
  SDK revision also exposes the clearer `mpesa_express_payment` and
  `mpesa_express_query` names.
- The app uses the SDK's M-Pesa Express query. It does not use the separate
  generic `transation_status_request` method for STK status.
- Callback data is not treated as authentication. Only the authenticated
  query and strict correlation can update an attempt.
- Provider credentials and checkout payloads are never returned by the API.
- The sandbox result does not authorize production credentials, tenant live
  shortcode connections, pooled settlement, refunds, or disbursements.

Safaricom describes Daraja APIs as asynchronous and lists M-Pesa Express
separately from Transaction Status in its [API catalogue](https://developer.safaricom.co.ke/apis)
and [Getting Started guide](https://developer.safaricom.co.ke/apis/GettingStarted).
Confirm the query response contract with the Daraja sandbox simulator before
enabling automatic financial receipt creation.
