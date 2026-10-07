# ADR-002: First provider-backed invoice payments

**Status:** Accepted as a provisional Safaricom Daraja sandbox direction for Kenya; no live tenant onboarding model is approved

**Date:** 6 October 2026

**Decision owner:** Founder

## Context

Tridim Business already records manual receipts, allocations, reversals, and finance exports. Issue #23 evaluates how to add provider-backed invoice collection while preserving that source of truth. A provider callback can be duplicated, delayed, forged, or delivered while the application is unavailable. An M-Pesa Express prompt avoids handling card data, but does not remove the need to verify status, protect shortcode-scoped credentials, handle retries, and reconcile exceptions.

The product has global ambitions and Kenya is a candidate market, not a confirmed exclusive beachhead. One connector must not be presented as global payment coverage.

## Candidate comparison

| Candidate | Evidence from official documentation | Fit and limitation |
|---|---|---|
| **Safaricom Daraja (M-Pesa)** | Daraja lists M-Pesa Express (Prompt) for a business to initiate a Paybill/Till payment from a customer's account, with an M-Pesa Express query for checking the resulting STK checkout. Its separate Transaction Status API covers broader account-transaction status checks. The sandbox uses a Daraja app and simulator; production setup is associated with a live business shortcode and organization-admin/operator access. | Best first sandbox candidate for Kenya-focused invoice collection and tenant-direct settlement. Production onboarding appears tied to a merchant shortcode. Public docs do not settle whether one SaaS integration may connect and operate many independently owned tenant shortcodes or how those tenant accounts should authorize the integration. No global coverage claim. |
| **Flutterwave** | Its documentation describes account-specific server credentials and payment methods across multiple markets, while its split-payments flow is framed for aggregators/marketplaces. | Defer for now. It may be reconsidered for other markets after confirming terms, account connection, onboarding, and operating responsibilities. |
| **Pesapal** | API 3.0 supports hosted order submission, registered IPN callbacks, a demo environment, and transaction-status retrieval after callback/IPN. | Credible alternative for hosted Kenya-oriented collection. Reassess if direct Daraja onboarding or integration does not fit the tenant model. |

This comparison is a technical fit check, not a commercial, legal, compliance, or market validation. Provider availability, eligibility, pricing, fees, and terms may vary by merchant and change over time; verify them directly before relying on them.

## Decision

Use **Safaricom Daraja M-Pesa Express (STK Push) as the first sandbox connector candidate** for customer invoice collection by Kenya-based tenants, behind the existing provider-neutral payment-attempt and event boundary. Use only synthetic data and sandbox credentials. Flutterwave is deferred, not removed from future consideration. Keep the global product strategy and add other country/provider adapters when justified.

The intended production model is that each tenant uses its own eligible Paybill/Till shortcode and receives settlement to its own merchant account. Do not route tenant funds through a Tridim-owned shortcode, pool collections, or initiate payouts. Safaricom's public Daraja material describes how APIs work and how to attach an app to a live shortcode, but does not confirm that a multi-tenant SaaS may connect many tenants' accounts under this model. Before any live tenant connection, obtain written Safaricom confirmation covering platform eligibility, per-tenant authorization and credentials, shortcode onboarding, production approvals, settlement, disputes/reversals, callback registration, and operational responsibilities. If that model is not approved, defer provider-backed tenant payments and continue manual receipts while evaluating hosted payment links or another provider.

## Daraja sandbox boundary

- Use Daraja's test environment and simulator with synthetic tenants, customers, and invoices. Keep test app credentials separate from any production credential path.
- The initial connector scope is M-Pesa Express (STK Push) initiation, durable asynchronous callbacks, and status verification through the M-Pesa Express query using its `CheckoutRequestID`. Do not use the separate, general Transaction Status API to verify an STK checkout. C2B paybill callbacks may be evaluated as a separate payment-entry flow only after its tenant shortcode binding and URL registration behavior are understood.
- The sandbox result does not establish that a tenant is eligible for a live Paybill/Till, that Tridim is approved as a SaaS integrator, or that each tenant can independently authorize the platform.
- Do not implement B2C disbursements, transfers, pooled settlement, Tridim-as-merchant, or live tenant credentials in this initial slice.

## Domain and event boundary

- The existing organization-scoped invoice, payment, allocation, and audit records remain the financial source of truth. Provider-specific payloads and identifiers belong to a separate, durable, tenant-scoped provider-attempt/event record; never store card numbers or security codes.
- Create a local payment attempt for one issued invoice with an immutable expected organization, invoice, customer, amount, currency, and local idempotency key before starting a hosted checkout or M-Pesa payment prompt.
- Treat browser redirects and callbacks as notifications only. Daraja callbacks are asynchronous and must not directly create receipts. Correlate the callback's `CheckoutRequestID` to the local attempt, then retrieve status through the authenticated M-Pesa Express query before marking an attempt successful. Match provider request IDs, the local attempt, expected amount, currency, and configured sandbox shortcode; mismatches and unverifiable events go to a recoverable exception queue.
- Store a provider event durably before acknowledging it. Deduplicate on the provider's stable event/transaction identity within the provider account scope. Process state transitions atomically; retries must return the existing result and never create duplicate receipts or allocations.
- Pending events remain pending and are checked again on a bounded schedule. Failed verification, unknown attempts, amount/currency/account mismatches, exhausted retries, and out-of-order transitions remain visible with reason, timestamps, retry history, and a safe manual recovery path.
- After strict status and callback correlation, mark the attempt successful. Finance records its receipt through the existing finance workflow using the checkout request ID as reference; invoice allocation remains explicit and follows the existing same-organization, same-customer, same-currency and exact-amount rules. This sandbox slice does not automatically create ledger receipts until the Daraja query response contract has been confirmed in the simulator.
- A verified refund or reversal is not an ordinary failed payment. Preserve the original payment and event history; reconcile it as a distinct exception/adjustment workflow. Do not automatically delete or overwrite allocations. The implementation issue must define atomic reversal/adjustment behavior before supporting refunds or chargebacks.
- Monitor callback failures and query pending attempts through the provider status API. Provider notifications are not a substitute for periodic reconciliation.

## Scope and safeguards

The first sandbox slice may cover M-Pesa Express/STK Push initiation, attempt creation, authenticated M-Pesa Express query verification keyed by `CheckoutRequestID`, durable callback intake, idempotency, and an operator-visible exception/retry view. The general Transaction Status API is a distinct Daraja capability and is not the STK checkout verification step. The slice must use synthetic customers/invoices and sandbox credentials.

Out of scope: custody or pooling of funds, payouts, marketplace/split-payment routing, Tridim acting as merchant of record, card-data handling, automatic multi-invoice allocation, tax/accounting claims, refunds/chargebacks, live activation, and country-specific compliance claims. These require separate design and review.

## Consequences and prerequisites

- The adapter boundary allows a later provider without duplicating core receipts, allocations, or finance exports.
- Provider-specific amounts and settlement rules may not match the app's current five-decimal internal arithmetic. Define currency minor-unit validation, rounding, fees, and settlement reconciliation before issuing customer-facing payment amounts.
- Credential encryption, access control, rotation, and deletion need a dedicated security design before storing merchant secrets. No credentials belong in source control, logs, or browser code.
- Provider integration does not change the product's global readiness or establish legal, tax, privacy, accounting, or payment compliance in any country.

## References

- Safaricom Daraja [API catalogue](https://developer.safaricom.co.ke/apis) — M-Pesa Express, C2B, transaction status, and other APIs.
- Safaricom Daraja [Getting Started](https://developer.safaricom.co.ke/apis/GettingStarted) — account/app setup and asynchronous callback guidance.
- Safaricom Daraja [Customer to Business](https://developer.safaricom.co.ke/apis/CustomerToBusiness) — C2B shortcode integration and callbacks.
- Safaricom Daraja [M-Pesa Express (Prompt)](https://developer.safaricom.co.ke/apis) — STK Push initiation and checkout query capability.
- Safaricom Daraja [Transaction Status](https://developer.safaricom.co.ke/apis/TransactionStatus) — separate general transaction-status API, not the M-Pesa Express query.
- Safaricom Daraja [Business to Customer](https://developer.safaricom.co.ke/apis/BusinessToCustomer) — live shortcode/admin setup details (B2C is not in this connector's scope).
- [Flutterwave authentication](https://developer.flutterwave.com/docs/authentication) and [split payments](https://developer.flutterwave.com/docs/split-payments) — retained as future comparison references, not the selected connector.
- [Pesapal API 3.0 IPN registration](https://developer.pesapal.com/how-to-integrate/e-commerce/api-30-json/registeripnurl) and [order submission](https://developer.pesapal.com/how-to-integrate/e-commerce/api-30-json/submitorderrequest) — alternative hosted collection flow.

Documentation reviewed 6 October 2026. Confirm current Daraja docs and written merchant/platform terms again before live onboarding.
