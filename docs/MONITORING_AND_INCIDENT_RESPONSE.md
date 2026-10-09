# Monitoring and Incident Response

**Status:** Core guidance for internal alpha; deployment-specific alerting and named ownership are not yet configured

This runbook describes what to observe and how to respond for the public Tridim Business platform. It does not imply that a cloud project, alert channel, on-call rota, service-level objective, or production payment integration exists.

## Health endpoints

| Endpoint | Expected result | Use |
|---|---|---|
| `GET /health/live/` | `200` with body `ok` | The web process can answer requests. It intentionally does not query dependencies. |
| `GET /health/ready/` | `200` with body `ok`; `503` with body `unavailable` if the default database connection fails | The service can accept work that requires its database. |

Both endpoints are unauthenticated and disclose no dependency details. Restrict probe access at the network edge if the deployment platform allows it. Use liveness to detect a stuck process; use readiness to stop routing work to an instance that cannot reach its database. Avoid aggressive restart loops for database outages.

## Minimum signals to configure

Select a monitoring provider and tune thresholds after observing the deployed service. Start with these signals:

| Signal | What to alert on | Initial response |
|---|---|---|
| Availability | Repeated failed liveness probes or externally observed request failures | Check deployment health, recent changes, and service logs; use readiness to distinguish application process from database trouble. |
| Request health | Sustained 5xx rate or latency above an agreed threshold | Identify affected routes and release window. Do not log request bodies or authorization headers. |
| Database | Readiness failures, connection exhaustion, storage pressure, or database errors | Check database availability and capacity; follow [Database Backup and Restore](DATABASE_BACKUP_AND_RESTORE.md) for recovery decisions. |
| Backups | Failed backup jobs or backup age beyond the approved recovery objective | Confirm the last successful backup and escalate before making destructive changes. A restore rehearsal is not proof that hosted backups are configured. |
| Scheduled cleanup | `cleanup_abuse_records` command failure or missed execution | Check scheduler history and command exit status; retry only after understanding repeated-failure effects. |
| Authentication abuse | Sudden increases in rejected or rate-limited login attempts | Check aggregate rates and edge protections; do not alert with raw usernames, IP addresses, or password data. |
| Daraja sandbox callbacks | Callback error-rate changes, rate-limit events, or unresolved attempts requiring reconciliation | Confirm this is sandbox traffic; inspect safe event identifiers and status only. Do not log callback payloads, phone numbers, credentials, or passkeys. |

Prefer counters, durations, status classes, and opaque correlation identifiers. Keep user-entered content, access tokens, session cookies, passwords, payment secrets, full phone numbers, and callback bodies out of logs, traces, alert names, and ticket titles. Apply access controls and retention limits to telemetry.

The repository does not currently provide a metrics exporter or central log pipeline. These endpoint contracts and signal definitions are provider-neutral; the chosen deployment must wire them to its actual probe, log, metric, and alert mechanisms.

## Incident response

### Severity guidance

- **SEV 1 — Critical:** broad service outage, suspected unauthorized access or data exposure, or financial records may be corrupted. Start incident coordination immediately; contain access or traffic where needed and preserve evidence.
- **SEV 2 — Major:** a core workflow is unavailable for multiple users, database availability is degraded, or backups/recovery may be at risk. Assign an incident lead and technical responder promptly.
- **SEV 3 — Limited:** a contained feature issue or one-user impact with a safe workaround. Record the issue, provide the workaround, and schedule a fix.

These are suggested internal categories, not customer-facing response-time commitments. Final severity thresholds and response expectations must be agreed before field evaluation.

### Response steps

1. **Acknowledge and assign.** Record when the alert was received, severity, incident lead, technical responder, and a private coordination channel.
2. **Establish impact.** Identify affected service areas, tenant scope, start time, and whether confidentiality, integrity, or availability may be affected. Use aggregate telemetry and approved audit records.
3. **Contain safely.** Use the smallest reversible action that limits ongoing impact. Preserve relevant logs and audit events. Do not disable tenant isolation, authentication, backups, or payment verification as a shortcut.
4. **Recover.** Check recent releases and dependency health. Roll back only when the release is a likely cause and the rollback is safe for the current schema. For data recovery, follow the backup/restore runbook and record the chosen recovery point.
5. **Communicate.** Use the approved private channel for responders. Customer or regulator communications require the accountable business/privacy owner and applicable review; no notification deadline is asserted here.
6. **Close and learn.** Confirm service recovery with health checks and a relevant synthetic workflow. Record timeline, impact, cause if known, recovery actions, data handling, follow-ups, and owners. Review actions without assigning blame.

## Ownership and deployment decisions

Complete these fields before any real customer data or field evaluation:

| Responsibility / decision | Current status |
|---|---|
| Business/service owner and contact | **TBD — assign a named accountable person and backup** |
| Technical operator and incident lead coverage | **TBD — name responders and define coverage hours** |
| Privacy/security escalation contact | **TBD — assign a reviewer and escalation path** |
| Alert destination and access list | **TBD — choose a monitored private channel and test delivery** |
| Hosting provider, project, and region | **TBD — see [ADR-004](ADR-004-HOSTING-AND-PAYMENT-ACCOUNTS.md)** |
| Monitoring/logging provider and retention | **TBD — select, configure, and review access/retention** |
| Alert thresholds and service objectives | **TBD — baseline first; approve targets before field evaluation** |
| RPO, RTO, backup retention, and hosted PITR | **TBD — define and verify against the selected hosting service** |
| Daraja production approval and support | **Not enabled — sandbox only; live use requires separate readiness and provider approval** |

Keep the owner list and alert tests current. After each incident or deployment change, verify that the contact path still works. Support access to application data must follow [Admin Support Access](ADMIN_SUPPORT_ACCESS.md).
