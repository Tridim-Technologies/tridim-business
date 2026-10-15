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

Cloud Monitoring and Cloud Logging are the preferred future monitoring direction. Neither is configured for this project. Tune thresholds after observing a deployed service, and start with these signals:

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

## Ownership, handoff, and escalation

The roles below define the required handoff; they are not assigned people or an active on-call service. The internal alpha remains limited to local synthetic data until each owner, backup, coverage window, and contact route is assigned and tested.

| Role | Accountable responsibilities | Primary / backup | Current state |
|---|---|---|---|
| Business/service owner | Owns business impact and severity decisions; approves service-level recovery or suspension; coordinates stakeholder updates; approves any external communication with the privacy/security reviewer. | **TBD / TBD** | Unassigned |
| Technical operator / incident lead | Receives operational alerts; opens the incident record; coordinates technical response; selects safe containment; owns service recovery and technical timeline; hands database restore to an authorized recovery operator. | **TBD / TBD** | Unassigned |
| Privacy/security reviewer | Leads assessment of suspected disclosure, unauthorized access, or integrity compromise; preserves evidence and advises on access containment; advises the business owner on applicable notification and legal review. | **TBD / TBD** | Unassigned |
| Recovery operator | Performs approved backup/restore actions, records the recovery point and validation evidence, and gets data-owner approval before cutover or cleanup. This can be the technical operator only if that assignment is explicit. | **TBD / TBD** | Unassigned |

### Escalation sequence

1. **Receive and record.** The designated primary technical operator acknowledges the report through the monitored private alert destination or incident-report route, records the time and safe summary, and assigns an incident identifier. The destination, access list, and acknowledgement expectations are **TBD**; no monitored route is configured today.
2. **Classify and lead.** The technical operator starts as incident lead, identifies affected services and tenants from approved metadata, and classifies severity using the guidance above. The business/service owner confirms business impact and may raise severity.
3. **Escalate by impact.** For **SEV 1**, suspected exposure/unauthorized access, or possible financial-record corruption, notify the business/service owner and privacy/security reviewer immediately through the private route; keep the technical operator coordinating containment and evidence preservation. For **SEV 2**, notify the business/service owner and technical backup promptly and engage the recovery operator if data recovery is possible. For **SEV 3**, the technical operator records the issue, assigns a remediation owner, and provides the approved workaround. If the primary is unavailable, the named backup takes the same role; until coverage and response intervals are assigned, no response-time promise is made.
4. **Contain and recover.** The incident lead chooses the smallest reversible containment action. The privacy/security reviewer leads the suspected-data-exposure assessment. Database restore requires an explicitly authorized recovery operator and follows [Database Backup and Restore](DATABASE_BACKUP_AND_RESTORE.md); record approval before restore and cutover.
5. **Approve communications and close.** The business/service owner owns stakeholder updates. The privacy/security reviewer advises on external, customer, or regulator communication and required review; only the accountable owner authorizes release. Record recovery evidence, impact, data-handling decisions, and follow-up owners before closing.

Incident records must use the minimum necessary information: incident ID, timestamps, severity, affected service/tenant scope, role assignments, actions, decisions, and opaque audit/event identifiers. Do not copy expense evidence, payment callback bodies, credentials, full phone numbers, or other sensitive payloads into alert text, chat, or issue titles. Preserve source logs and audit records under their existing access and retention controls.

### Ownership and deployment decisions

Complete these assignments and verify the contact path before any real customer data or field evaluation:

| Responsibility / decision | Current status |
|---|---|
| Business/service owner and backup | **TBD — assign named people** |
| Technical operator / incident lead and backup | **TBD — assign named people** |
| Privacy/security reviewer and backup | **TBD — assign named people and escalation route** |
| Recovery operator and restore/cutover approver | **TBD — assign named people and approval handoff** |
| Coverage hours and primary-to-backup response interval | **TBD — agree before evaluation; no response target is currently promised** |
| Alert destination, incident-report route, and access list | **TBD — choose a private monitored route and test delivery/backup handoff** |
| Hosting provider, project, and region | **TBD — deployment deferred; see [ADR-004](ADR-004-HOSTING-AND-PAYMENT-ACCOUNTS.md)** |
| Monitoring/logging direction | **Cloud Monitoring and Cloud Logging preferred; no project or services configured** |
| Telemetry retention and access policy | **TBD — review and configure before evaluation** |
| Alert thresholds and service objectives | **TBD — baseline first; approve targets before field evaluation** |
| Internal-alpha recovery planning targets | **Selected: RPO up to 24 hours, RTO by next business day, seven-day recovery window; not customer commitments** |
| Hosted recovery configuration and verification | **TBD — not configured; see [Database Backup and Restore](DATABASE_BACKUP_AND_RESTORE.md)** |
| Daraja production approval and support | **Not enabled — sandbox only; live use requires separate readiness and provider approval** |

Review the owner list and test alert delivery and backup handoff before real-data evaluation, and after any material contact or deployment change. Support access to application data must follow [Admin Support Access](ADMIN_SUPPORT_ACCESS.md).
