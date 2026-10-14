# Daraja sandbox invoice payment attempts

The first connector uses Safaricom Daraja **M-Pesa Express (STK Push)** for
prompt initiation and the matching **M-Pesa Express query** with
`CheckoutRequestID` for status checks. The general Daraja Transaction Status
API is a separate capability and is not used for STK checkout verification.

This is a sandbox integration only. Use synthetic organizations, customers,
invoices, and Daraja sandbox credentials. For a handset test, enter only a
phone number you control; do not use a customer number. The app rejects a
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

## Finance UI flow

Owners, admins, and finance members can open **Invoices** and start a sandbox
M-Pesa Express attempt on an issued KES invoice with available balance. Enter
a Kenyan phone number and a whole-KES amount no greater than the available
balance, then confirm the browser prompt. The attempt and its status remain
visible on that invoice after reloading the page. Choose **Refresh status** to
retry verification through the M-Pesa Express query after a callback has been
stored. A query acknowledgement without a final result leaves the attempt
pending.

The normalized phone number is stored on the attempt so the provider result can
be checked against the original request. It is not returned by the attempt
listing API or shown in the UI. Use only a phone number you control for this
sandbox test. Sandbox attempts are not live payments and do not create finance
receipts.

When an attempt is confirmed as successful, record the receipt through the
existing **Payment receipts** workflow. Select the invoice customer, use the
confirmed amount, choose **Mobile money**, and use the attempt's checkout
reference as the receipt reference. Then allocate that receipt to the invoice.

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
   Finance can also reload attempts for that invoice with `GET` on the
   initiation endpoint.
4. Daraja posts an asynchronous callback to the configured URL. The app stores
   a minimized callback summary with a hash of the payer number, deduplicates
   by `CheckoutRequestID`, and queries M-Pesa Express using that ID. A callback
   alone never marks a payment successful.
5. The app first requires the query response to echo the stored checkout and
   merchant request IDs. A matching query response without a final `ResultCode`
   (for example, an acceptance response with `ResponseCode` and
   `ResponseDescription`) leaves the attempt pending. **Refresh status** retries
   the query for a stored callback. A final response must agree with the
   callback result; success also requires the callback amount and phone hash to
   match the immutable attempt. Identifier or final-result mismatches remain in
   `review`; they do not create a ledger receipt.
6. A confirmed provider success is visible on the attempt. Finance records the
   receipt through the existing payment workflow using the checkout request ID
   as its reference, then explicitly allocates that receipt to the invoice.
   This release does not automatically create or allocate a `Payment` from a
   provider callback.

The **Refresh status** action retries status verification for an attempt with a
stored callback using `POST` on
`/api/organizations/{organization_id}/daraja/sandbox-attempts/{attempt_id}/reconcile/`.
The endpoint requires the same organization finance authorization as other
payment operations. An attempt without a checkout ID or callback cannot be
retried automatically and returns a conflict response. A non-final query keeps
the callback event unprocessed so a later refresh can query it again.

## Safety boundary

- The app installs `mpesa-sdk` 1.1.0 or a compatible later 1.x release from
  PyPI. It calls `mpesa_express_payment` and `mpesa_express_query`; the SDK
  retains `lipa_na_mpesa_online_payment` and `lipa_na_mpesa_online_query` as
  compatibility aliases.
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
