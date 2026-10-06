# ADR-002: First provider-backed invoice payments

**Status:** Accepted as a provisional sandbox direction; no production provider or merchant onboarding model is approved

**Date:** 6 October 2026

**Decision owner:** Founder

## Context

Tridim Business already records manual receipts, allocations, reversals, and finance exports. Issue #23 evaluates how to add provider-backed invoice collection while preserving that source of truth. A provider callback can be duplicated, delayed, forged, or delivered while the application is unavailable. A hosted checkout reduces exposure to card data, but does not remove the need to verify status, protect credentials, handle retries, and reconcile exceptions.

The product has global ambitions and Kenya is a candidate market, not a confirmed exclusive beachhead. One connector must not be presented as global payment coverage.

## Candidate comparison

| Candidate | Evidence from official documentation | Fit and limitation |
|---|---|---|
| **Flutterwave** | Its payment-method guide lists KES with card and M-Pesa, plus region-specific methods across several other markets. Its webhook guide describes signature checks, idempotent processing, fast acknowledgement, and status polling/verification when callbacks fail. Its Kenya onboarding guide describes merchant verification and collection/payout requirements. | Best provisional sandbox candidate for the existing Kenya-candidate context and local M-Pesa need, with a documented path to other regional methods and international cards. Account-per-tenant onboarding, platform/SaaS terms, and merchant credential connection still need direct confirmation. It does not satisfy the global ambition by itself. |
| **Pesapal** | API 3.0 supports hosted order submission, registered IPN callbacks, a demo environment, and transaction-status retrieval after callback/IPN. | Credible alternative for a Kenya-oriented hosted collection flow. Current official material inspected here does not establish a stronger fit for the product's broader global ambition or confirm an account-connection model for a multi-tenant SaaS. |

This comparison is a technical fit check, not a commercial, legal, compliance, or market validation. Provider availability, eligibility, pricing, fees, and terms may vary by merchant and change over time; verify them directly before relying on them.

## Decision

Use **Flutterwave as the first sandbox connector candidate**, behind a provider-neutral payment-attempt and event boundary. This is provisional and limited to synthetic data and sandbox credentials. Do not enable live payments or promise production support based on this ADR.

Before implementing merchant account connection or any live flow, the account owner must confirm with Flutterwave that each customer business can connect and operate its own merchant account for this SaaS use case, and must verify current platform terms, supported merchant countries, checkout/callback behavior, event verification, refund behavior, and credential-management requirements. If independent merchant accounts cannot be safely supported, defer the connector and reassess hosted payment links or another provider. Do not route tenant funds through a Tridim-owned merchant account.

## Domain and event boundary

- The existing organization-scoped invoice, payment, allocation, and audit records remain the financial source of truth. Provider-specific payloads and identifiers belong to a separate, durable, tenant-scoped provider-attempt/event record; never store card numbers or security codes.
- Create a local payment attempt for one issued invoice with an immutable expected organization, invoice, customer, amount, currency, and local idempotency key before redirecting to hosted checkout.
- Treat browser redirects and callbacks as notifications only. Verify provider signatures according to current provider documentation, then retrieve the transaction status from the provider's authenticated status endpoint before recording a successful receipt. Match provider merchant/account, local attempt, amount, and currency exactly; mismatches and unverifiable events go to a recoverable exception queue.
- Store a provider event durably before acknowledging it. Deduplicate on the provider's stable event/transaction identity within the provider account scope. Process state transitions atomically; retries must return the existing result and never create duplicate receipts or allocations.
- Pending events remain pending and are checked again on a bounded schedule. Failed verification, unknown attempts, amount/currency/account mismatches, exhausted retries, and out-of-order transitions remain visible with reason, timestamps, retry history, and a safe manual recovery path.
- Provider success creates one payment receipt only after verification. Invoice allocation remains explicit and follows the existing same-organization, same-customer, same-currency and exact-amount rules. The initial connector must not silently allocate excess or unmatched funds: keep the receipt unapplied and visible for finance review.
- A verified refund or reversal is not an ordinary failed payment. Preserve the original payment and event history; reconcile it as a distinct exception/adjustment workflow. Do not automatically delete or overwrite allocations. The implementation issue must define atomic reversal/adjustment behavior before supporting refunds or chargebacks.
- Monitor callback failures and query pending attempts through the provider status API. Provider notifications are not a substitute for periodic reconciliation.

## Scope and safeguards

The first sandbox slice may cover hosted checkout, attempt creation, authenticated status verification, durable event intake, idempotency, and an operator-visible exception/retry view. It must use synthetic customers/invoices and sandbox credentials.

Out of scope: custody or pooling of funds, payouts, marketplace/split-payment routing, Tridim acting as merchant of record, card-data handling, automatic multi-invoice allocation, tax/accounting claims, refunds/chargebacks, live activation, and country-specific compliance claims. These require separate design and review.

## Consequences and prerequisites

- The adapter boundary allows a later provider without duplicating core receipts, allocations, or finance exports.
- Provider-specific amounts and settlement rules may not match the app's current five-decimal internal arithmetic. Define currency minor-unit validation, rounding, fees, and settlement reconciliation before issuing customer-facing payment amounts.
- Credential encryption, access control, rotation, and deletion need a dedicated security design before storing merchant secrets. No credentials belong in source control, logs, or browser code.
- Provider integration does not change the product's global readiness or establish legal, tax, privacy, accounting, or payment compliance in any country.

## References

- [Flutterwave payment methods](https://developer.flutterwave.com/v3.0.0/docs/payment-methods) — KES/card/M-Pesa and region-specific payment methods.
- [Flutterwave webhooks](https://developer.flutterwave.com/v4.0/docs/webhooks) — signature guidance, idempotency, prompt acknowledgement, retries, and status polling.
- [Flutterwave Kenya onboarding requirements](https://www.flutterwave.com/us/support/onboarding/onboarding-requirements-for-using-flutterwave-in-kenya) — merchant verification and collection/payout prerequisites.
- [Pesapal API 3.0 IPN registration](https://developer.pesapal.com/how-to-integrate/e-commerce/api-30-json/registeripnurl) — registered notification endpoint and IPN identifier.
- [Pesapal API 3.0 order submission](https://developer.pesapal.com/how-to-integrate/e-commerce/api-30-json/submitorderrequest) — hosted checkout callback and transaction-status lookup.

Documentation reviewed 6 October 2026. Confirm current provider documentation and account terms again when implementation begins.
