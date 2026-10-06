# ADR-003: Tenant payment-account credentials

**Status:** Accepted for design and sandbox boundaries; production storage vendor and deployment are undecided

**Date:** 6 October 2026

**Decision owner:** Founder

## Context

ADR-002 names Flutterwave as a provisional sandbox candidate, subject to confirming that customer businesses can use their own accounts with this SaaS. No hosting provider or deployment topology has been chosen; Kubernetes is only a possible target. Provider secret keys are bearer credentials: exposure can permit payment actions under the merchant account.

This decision covers the product's handling of tenant-specific payment-provider credentials. It does not select a hosting vendor, secret-manager product, customer identity-verification process, or provider account-connection mechanism.

## Assets and trust boundaries

- Merchant API secrets, provider account identities, payment attempts, invoices, and audit records.
- Tenant administrators who connect, rotate, or disconnect a provider account.
- The Django application and its payment-processing worker, which may need short-lived access to a merchant secret to call the provider.
- The database, deployment configuration, secret-management service, CI system, logs, backups, and operations personnel.

A provider credential can be used only for its linked organization and provider connection. Client-supplied organization IDs, connection IDs, or secret references are untrusted selectors; authorization and resolution must be performed server-side from the authenticated organization context and the payment attempt.

## Decision

Define a provider-neutral `PaymentCredentialStore` boundary. In a production multi-tenant service, store provider secret material in an external secret-management service and store only an opaque, non-secret reference plus connection metadata in the application database. Do not place tenant-specific provider credentials in normal database columns, Kubernetes Secret objects, application settings, or environment variables.

Only the backend payment-processing component may resolve a credential, and only after it has loaded and authorized the provider connection through the attempt's organization. The client never receives the credential or reference. The reference is generated and bound by the server; API callers cannot choose or substitute it. Resolve credentials just in time, keep plaintext in memory only for the provider request, and never write it to logs, traces, error messages, analytics, exports, or cache. The payment component's external identity must have the narrowest available read access; record secret access in the secret manager's audit trail.

This boundary is vendor-neutral. Select the concrete manager and workload identity only after hosting and operational ownership are chosen. If the selected service cannot provide protected storage, authenticated workload access, access auditing, revocation, and a recoverable rotation process, provider-account connection remains disabled.

## Connection lifecycle

1. An owner or explicitly authorized finance administrator starts connection from within the selected organization. A provider authorization flow with short-lived, single-use state and callback validation is preferred if the provider supports a suitable merchant authorization model. If the provider instead requires an API key, accept it only in a one-time HTTPS request to the backend; do not persist it before validation.
2. The server validates the credential with a non-financial provider identity/status operation where available. It checks that the provider account identity and supported environment match the connection. It never performs a charge as a credential test.
3. The server writes the secret to the secret manager and stores its opaque reference, provider, provider-account identifier, environment, status, connecting actor, timestamps, and secret version metadata in the tenant-scoped database record. Return only masked/non-secret account metadata.
4. Payment attempts bind to an active server-side connection record. A request cannot supply the provider credential reference or cause lookup in another tenant's secret namespace. Check organization membership and finance permission for create, read, rotate, and disconnect actions.
5. Rotation validates a new credential first, creates a new secret version, switches the connection pointer atomically, verifies a non-financial operation, then revokes/deletes the old provider key and secret version as appropriate. If safe overlap is impossible, mark the connection unavailable during the controlled rotation window; do not silently fall back to an old key.
6. Disconnect disables new payment attempts immediately, stops retries that require provider access, records the actor/reason, revokes the provider key where possible, and schedules deletion of the stored secret according to a documented retention process. Deleting the connection must not delete invoices, receipts, provider event history, or audit records.

## Development and CI

- Local development may use a dedicated provider sandbox credential supplied from an ignored local environment file or process environment. It must be a sandbox-only credential, never a production merchant key; the application must not log its value.
- Tests use fake provider and credential-store implementations by default. CI does not need live provider credentials and must not call the provider in ordinary pull-request workflows.
- Any future sandbox integration test must require an explicitly configured sandbox credential and sandbox endpoint, use synthetic records, and fail closed when the environment is ambiguous. Production endpoints and credentials must not be accepted by that test path.
- Never store secrets in source control, issue text, fixtures, screenshots, support tickets, build artifacts, container layers, or test output. If a secret is exposed, disable the connection, revoke the provider key, investigate access, and remove exposed copies from logs and artifacts where supported.

## Kubernetes implications

Kubernetes Secret values are base64 encoded and, by default, stored unencrypted in etcd. If native Kubernetes Secrets are used for workload-level configuration such as the secret-manager bootstrap identity, cluster operators must enable encryption at rest, tightly scope RBAC and pod access, protect etcd and backups, and prevent broad list/watch access. Do not use one Kubernetes Secret per tenant merchant API key: it creates a cluster-configuration credential inventory and makes tenant lifecycle, authorization, access auditing, and revocation harder to enforce in the application.

If the product is deployed to Kubernetes, workload identity should authenticate the payment component to the external secret manager without a long-lived bootstrap key where the platform supports it. A Secrets Store CSI integration is an option for mounted workload configuration, but the application-facing tenant-credential lookup still needs the authorized server-side boundary described above. Kubernetes is not required by this ADR.

## Threats and required controls

| Threat | Required control |
|---|---|
| Cross-tenant IDOR or a forged secret reference | Resolve an active connection only through the authenticated organization and authorized payment attempt; reject caller-supplied references; add adversarial cross-tenant tests for every connection operation. |
| Database dump or backup exposure | Store only opaque references and non-secret metadata in the database. Protect the external secret manager and its backups separately. |
| Application or payment-worker compromise | Keep payment-specific permissions separate where practical; grant only required secret reads; restrict outbound destinations; audit lookups; rotate/revoke credentials and suspend affected connections during response. Secrets in process memory remain exposed to a compromised process and must be treated as such. |
| Logs, traces, browser or support disclosure | Redact authorization headers, provider request/response bodies, submitted credentials, and secret-manager values at source; return masked metadata only; verify with tests. |
| Stale or orphaned references | Fail closed when a secret is missing, disabled, revoked, or unavailable; surface a recoverable connection exception; never switch to another tenant's credential or an implicit platform account. |
| Secret-store outage | Fail payment initiation safely; retain attempts/events for recovery; do not mark invoices paid or receipts successful from a failed lookup. |
| Credential rotation or suspected compromise | Support immediate disable/revoke, versioned rotation, audit history without values, an owner notification path, and verification that old credentials are no longer usable. |
| CI or local environment leakage | Keep credentials out of CI by default; restrict optional test credentials to dedicated sandbox contexts; ignore local secret files; avoid commands that print environment values. |

## Audit, deletion, and recovery

Audit connection creation, verification outcome, rotation, disable, disconnect, and secret-store access using tenant, actor, provider, connection ID, result, and timestamp. Never record the secret value, full authorization header, or unrestricted raw provider payload. Audit records remain subject to the product's retention policy.

Back up non-secret connection metadata and separately document the secret manager's backup/recovery method, key ownership, restore access, and deletion guarantees before production use. A restored database with missing credentials must leave connections disabled and visible until an authorized operator reconnects them. Deletion and provider revocation must cover active secret versions, replicas, and retained backups according to the selected service's verified controls.

## Consequences and open decisions

- A separate external manager supports independent lifecycle and access auditing and avoids placing merchant keys in the general business database. It adds operational cost, service dependency, and recovery work.
- No exact authorization flow can be implemented until Flutterwave confirms the supported account connection model and terms for this product. Do not assume OAuth, delegated accounts, or subaccounts are available.
- Hosting provider, external secret-manager product, workload identity, secret retention/deletion guarantees, operational owners, and production recovery objectives remain undecided.
- Before provider implementation, create a separate issue for the chosen account connection flow and production secret-store adapter; include database-reference integrity, permission tests, log redaction tests, rotation/revocation drills, and sandbox-only endpoint enforcement.
- This ADR does not authorize live payments, storing real merchant credentials, using a Tridim-owned merchant account, pooling funds, or production deployment.

## References

- [OWASP Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html) — centralized management, least privilege, lifecycle, rotation, revocation, and audit considerations.
- [Kubernetes Secrets good practices](https://kubernetes.io/docs/concepts/security/secrets-good-practices/) — encryption at rest, least-privilege access, and external stores.
- [Kubernetes Secrets](https://kubernetes.io/docs/concepts/configuration/secret/) — default etcd storage and minimum protection steps.
- [Kubernetes encryption at rest](https://kubernetes.io/docs/tasks/administer-cluster/encrypt-data/) — API resource encryption configuration and recovery considerations.
- [Django 6.0 security documentation](https://docs.djangoproject.com/en/6.0/topics/security/) — protect Django secret keys and account for deployment controls.

Documentation reviewed 6 October 2026. Verify current platform, provider, and secret-manager documentation when the deployment and implementation choices are made.
