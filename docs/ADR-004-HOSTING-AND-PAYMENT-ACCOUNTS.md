# ADR-004: Initial hosting target and tenant payment accounts

**Status:** Accepted as the initial hosted-deployment recommendation; production account, region, sizing, and rollout remain subject to readiness review

**Date:** 6 October 2026

**Decision owner:** Founder

## Context

ADR-001 keeps Tridim Business as a Django/PostgreSQL modular monolith and explicitly does not require Kubernetes. ADR-003 defines a provider-neutral `PaymentCredentialStore` and requires tenant payment credentials to live in an external secret manager. The project needs a practical hosted reference path without coupling domain logic to one cloud provider.

Flutterwave remains a provisional sandbox candidate in ADR-002. Its public documentation describes server API keys with broad merchant-account access and an aggregator/subaccount payment model. The public material reviewed for this ADR does not establish that an ordinary SaaS platform may let each tenant connect its own independently contracted merchant account through a delegated authorization flow. That commercial and technical permission must not be inferred.

## Decision

Use **Google Cloud Run + Cloud SQL for PostgreSQL + Secret Manager** as the recommended first hosted reference deployment, subject to cost, data-location, operational, and provider checks before real customer data or live payments. This is a pragmatic initial deployment path, not a requirement that the product run on Google Cloud or Kubernetes.

- Package Django and the web-facing service as a standard OCI container and run it on Cloud Run. Keep provider and cloud APIs out of core domain code.
- Use Cloud SQL for PostgreSQL. Cloud Run can scale application instances down when idle, but the database remains a provisioned service with ongoing cost. Size it against measured workload; do not describe a zero-cost production setup.
- Use a dedicated user-managed Cloud Run service identity and IAM rather than long-lived service-account key files or copied credentials. Grant the smallest useful permissions.
- Use Secret Manager for provider credentials, via the `PaymentCredentialStore` adapter. Store only opaque references and connection metadata in PostgreSQL. Resolve a secret only after the request has been bound to the authenticated tenant's authorized payment attempt. The shared service identity remains a coarse application boundary; secret references and tenant authorization checks must still be enforced in Django and audited.
- Prefer a regional secret-manager resource in the same deployment region when residency requirements allow. Document that regional resources do not automatically replicate and design recovery accordingly.
- Start with one region. Johannesburg (`africa-south1`) is a candidate for an Africa-focused early deployment, not a fixed selection: confirm customer latency, data-location obligations, provider availability, and region-specific pricing before provisioning. Do not claim this provides global or multi-region availability.
- Keep standard PostgreSQL, container, and storage interfaces so another host or a self-managed deployment can be supported without rewriting business rules. Add a different adapter only when an actual deployment need justifies it.
- Kubernetes remains optional. Reconsider it only if demonstrated operational needs such as workload placement, sustained scale, or platform constraints justify its additional operating burden.

For an early synthetic-data environment, a low-cost single-zone database may be useful for evaluation. Before any real-customer-data rollout, select a supported Cloud SQL configuration, define backups and retention, test restore, set recovery objectives, and review availability and monitoring. Cloud SQL shared-core machine types are not covered by its SLA, so they are not the recommended production choice for a customer-facing service. Exact sizing and recurring spend require workload measurement and a current regional quote.

## Payment account prerequisite

Do not build or advertise a tenant payment-account connection flow until the provider confirms in writing that the intended model is permitted and specifies the supported connection, merchant onboarding, settlement, disputes, and credential lifecycle requirements.

- Do not use Tridim's own API key to collect on behalf of tenants as an assumed substitute for tenant authorization.
- Do not use Flutterwave split payments/subaccounts as an assumed tenant-owned direct-merchant connection. Public Flutterwave documentation describes this as an aggregator/marketplace arrangement with platform responsibilities.
- Do not store a tenant credential in the ordinary application database, application environment, Kubernetes Secret, or client application. Preserve ADR-003 controls.
- Continue with manual payment recording and allocation until an approved provider route, onboarding, and operational responsibilities are established.
- If ordinary tenant-authorized connection is not supported on acceptable terms, evaluate another provider or a different non-custodial payment experience in a separate decision. Do not silently pool funds or create a platform payment account model.

Public documentation reviewed on 6 October 2026 cannot answer provider-specific eligibility or contractual questions. The founder must obtain a written answer from Flutterwave or select another provider before implementation; this ADR does not authorize external contact, production provisioning, live payments, or handling real merchant credentials.

## Consequences

- The team has a concrete first hosted deployment path while keeping the application portable and Kubernetes-optional.
- A managed database introduces a baseline recurring cost even when the web service scales down. Cost estimates must include database compute, storage, backups, network transfer, secret versions/accesses, observability, and support.
- A single region simplifies initial operations but does not provide global latency, regional failover, or disaster recovery by itself.
- Workload identity removes the need for a long-lived Cloud service-account key in the app, but a compromised application process can still request secrets allowed by its identity. Limit permissions, audit access, redact outputs, and practice rotation and recovery.
- The payment integration remains blocked on provider confirmation; manual receipts remain the supported payment path meanwhile.

## Revisit when

- Measured application traffic or availability needs show Cloud Run is no longer an appropriate fit.
- A target customer's data-residency, latency, procurement, or hosting requirement rules out the candidate region or provider.
- Workload measurements and a current estimate show materially better total cost or supportability elsewhere.
- Flutterwave provides written account-connection terms, or the project selects a different provider.
- The team has an operational owner and has completed database restore, secret rotation, access review, and incident-response exercises.

## References

Provider and platform documents reviewed 6 October 2026; re-check before implementation because terms, availability, and pricing may change.

- Flutterwave [Authentication](https://developer.flutterwave.com/docs/authentication) — server-side API key usage.
- Flutterwave [Split Payments](https://developer.flutterwave.com/docs/split-payments) — subaccount and aggregator flow.
- Flutterwave [Merchant Services Agreement](https://www.flutterwave.com/us/support/general/updated-merchant-services-agreement-msa) — merchant, ISO, and PayFac responsibilities.
- Google Cloud [Cloud Run locations](https://cloud.google.com/run/docs/locations) and [pricing](https://cloud.google.com/run/pricing) — region and cost details.
- Google Cloud [Cloud Run service identity](https://docs.cloud.google.com/run/docs/securing/service-identity) and [secrets configuration](https://docs.cloud.google.com/run/docs/configuring/services/secrets).
- Google Cloud [Cloud SQL PostgreSQL locations](https://cloud.google.com/sql/docs/postgres/locations), [high availability](https://docs.cloud.google.com/sql/docs/postgres/high-availability), and [pricing](https://cloud.google.com/sql/pricing).
- Google Cloud Secret Manager [locations](https://docs.cloud.google.com/secret-manager/docs/locations), [regional data residency](https://docs.cloud.google.com/secret-manager/regional-secrets/data-residency), and [pricing](https://cloud.google.com/secret-manager/pricing).
