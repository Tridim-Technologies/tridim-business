# Production expense-evidence recovery design

**Status:** Design evaluation only; provider-neutral orchestration contracts and synthetic failure tests are implemented, but no production provider or adapter is selected
**Last reviewed:** 20 October 2026
**Related decisions:** [ADR-005](ADR-005-EXPENSE-EVIDENCE-HANDLING.md), [database backup and restore](DATABASE_BACKUP_AND_RESTORE.md)

This document turns the provider-neutral requirements in ADR-005 into a reviewable production architecture and restore acceptance plan. It does not authorize real evidence, deployment, a cloud account, a retention duration, or spending. The local SQLite journal remains a synthetic-data rehearsal only.

The core application now exposes narrow storage and deletion-journal protocols for deletion orchestration and permits test adapters to be injected. Contract tests exercise intent-write, object-delete, and completion-write failures against synthetic local evidence. These interfaces make the local workflow testable; they do not represent a production adapter contract for exact object generations, independently protected checkpoints, replicas, or backup purge verification. Production remains gated on selecting and rehearsing those controls.

## Design objective

After a database or evidence-store restore, no deleted expense evidence may become available again. A restore must discover every deletion that could post-date the selected recovery point, purge every applicable object version and derivative, repair surviving database rows, and prove that replay reached a trustworthy journal checkpoint before evidence routes are enabled.

The design must also distinguish **inaccessible**, **delete requested**, **provider delete acknowledged**, and **permanently purged**. A delete marker, soft-delete state, expired application row, or accepted API request alone does not prove that older object versions, replicas, backups, or derivatives are gone.

## Ledger pattern evaluation

| Pattern | Assessment | Decision |
|---|---|---|
| Events in the application database | A restore to an earlier database point rolls the events back with the records they are meant to protect. | Reject as the sole recovery ledger. Application audit rows remain useful for business history, not as the independent restore source. |
| Separate table/database that shares the same administrator, credentials, backup schedule, and restore point | Physical separation alone does not prevent a coordinated rollback, credential compromise, or accidental restore of both copies. | Reject unless a future design proves separate administration, credentials, recovery points, and independent integrity anchoring. |
| Append-only ledger in a separately administered recovery boundary, with a separately protected signed checkpoint | Supports ordered events, idempotency, queries, and replay while a second trust boundary detects truncation or rollback. | Preferred architecture for provider evaluation. The ledger and checkpoint must not share the application database, evidence bucket, backup set, or ordinary application write identity. |
| Immutable object per event plus an independently protected signed sequence checkpoint | Can make event mutation difficult and keep the journal portable. Sequence allocation, atomic acknowledgement, concurrent writers, and replay queries need explicit design and fault tests. | Retain as a candidate implementation of the preferred architecture, not as a complete design by itself. |
| Provider audit logs, object notifications, or database timestamps alone | May be delayed, incomplete for application intent, subject to a separate retention policy, or unable to prove completion for an exact object generation. | Reject as the authoritative journal. They may supplement monitoring and forensic evidence. |

The preferred pattern is a design direction, not a vendor selection. A concrete implementation must document the administrative boundary, region, residency, availability, cost model, backup and retention controls, recovery identity, and failure semantics before implementation approval.

## Minimum production ledger contract

- Store intent before any object purge and wait for an acknowledged durable write. Ledger unavailability blocks deletion from being reported complete; keep the record inaccessible and raise a retryable operational condition.
- Assign a globally unique idempotency/event identifier and a strictly ordered sequence or equivalent monotonic cursor. Concurrent app instances must not create ambiguous ordering or reuse an identifier for different object metadata.
- Store only replay fields: opaque organization/evidence identifiers, opaque bucket/container and object key, immutable object generation/version identifiers, bounded reason code, server time, and intent/completion state. Do not store file names, receipt content, OCR text, free-form user notes, or credentials.
- Encrypt sensitive locators in transit and at rest; restrict read and write identities separately. Application credentials may append validated events but must not rewrite or erase existing events, change retention policy, or reset the checkpoint.
- Protect the sequence head with a signature or equivalent independently verifiable checkpoint held in a separately administered control plane. A checkpoint stored only beside the journal cannot detect rollback of both together.
- Verify event sequence, signatures/hashes, uniqueness, linkage between intent and completion, and the external checkpoint before replay. Missing, truncated, duplicated, reordered, or unverifiable history blocks access; do not guess a watermark from database timestamps.
- Make purge retries idempotent for the exact object generation. Record provider acknowledgement and independently verify its final state, including versions, snapshots, replicas, derivatives, soft-delete copies, and backup behavior covered by policy.
- Retain the journal and its checkpoints until every database/evidence backup capable of restoring a deleted version has expired or has itself been reconciled, and for any longer approved audit/legal requirement. The exact duration is undecided and must be aligned with customer retention and recovery policy.
- Provide availability and recovery targets that are at least sufficient for the chosen restore window. Alert on unavailable writes, age of the latest checkpoint, uncompleted intents, replay failures, and retention-policy drift without exposing object locators or receipt data.

## Object-store control evaluation

Versioning, soft delete, retention locks, backups, and permanent purge solve different problems. Every provider adapter must map these controls to a state machine and test the exact delete operation against a version identifier; generic `delete(key)` behavior is insufficient.

| Control | Recovery benefit | Deletion implication |
|---|---|---|
| Object versioning | Allows recovery of prior generations after overwrite or delete. | Every retained version that can restore the evidence must be located and purged or allowed to expire under a disclosed policy. Deleting the current name may leave older versions. |
| Soft delete / recycle retention | Allows recovery during a provider-defined window. | Data remains recoverable during the window and may not satisfy immediate permanent purge. Include the full window in deletion and backup disclosures. |
| WORM / retention lock / legal hold | Protects objects or journal events from alteration or deletion. | It can prevent evidence purge. Do not apply a lock to evidence objects unless the approved retention/legal policy explicitly requires it and the product communicates when deletion can complete. Ledger immutability and evidence immutability are separate decisions. |
| Managed backup / replication | Protects against service or operator failure. | A restore or replica may resurrect deleted bytes. Define whether deletion is propagated, how old copies expire, and whether the service exposes verifiable purge. |
| Generation/version preconditions | Binds a delete to the exact object version observed. | Required to avoid deleting a newer replacement or accidentally treating a delete marker as removal of the intended older version. |

Current official product documentation illustrates why the adapter contract cannot assume one universal behavior:

- Google Cloud Storage object versioning identifies generations and requires a generation-qualified request to delete a particular revision; soft delete retains deleted objects during its configured window, which defaults to seven days for supported new buckets. See [Object Versioning](https://docs.cloud.google.com/storage/docs/object-versioning), [delete an object](https://docs.cloud.google.com/storage/docs/json_api/v1/objects/delete), and [Soft Delete](https://docs.cloud.google.com/storage/docs/soft-delete).
- Amazon S3 Object Lock requires versioning. A delete marker can be added while a locked version remains protected, so deleting the current key is not evidence that the protected version was removed. See [Locking objects with Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html).
- Azure immutable blob policies prevent modification or deletion while the policy applies, while soft delete preserves a recoverable copy for its retention period. See [Immutable Storage](https://learn.microsoft.com/en-us/azure/storage/blobs/immutable-storage-overview) and [Soft Delete for Blobs](https://learn.microsoft.com/en-us/azure/storage/blobs/soft-delete-blob-overview).

These links were checked on 20 October 2026 and are examples for adapter discovery, not endorsements or a current product comparison. Re-check supported regions, API semantics, pricing, and feature interactions when a provider is actually considered.

## Proposed production deletion flow

1. Authorize the actor, check legal hold and retention policy, and commit the database state as `DELETION_PENDING`. Downloads, previews, exports, and downstream workflows must deny access immediately.
2. Append the minimal intent using an idempotency key. Wait for ledger acknowledgement and verify the sequence/checkpoint relationship.
3. Resolve the immutable object generation plus all policy-covered derivatives and replicas. If the provider cannot identify or delete each recoverable copy, keep evidence disabled for that deployment.
4. Request exact-generation purge. Handle already absent objects idempotently only after provider-specific semantics confirm that older versions and soft-deleted copies are accounted for.
5. Verify permanent purge or record the provider's explicitly retained state and expiry. Never label a temporarily recoverable object “permanently deleted.”
6. Append a completion event, advance and anchor the checkpoint, then mark the database row `DELETED`. A failure after step 4 is completed through idempotent verification and replay; the evidence remains inaccessible throughout.
7. Emit minimized operational metrics and audit results. Keep sensitive object locators out of routine logs and alerts.

## Restore replay and access gate

Keep evidence upload, preview, download, export, and evidence-dependent workflow actions disabled on the isolated restore target. This gate is independent of application startup and must not rely on an operator remembering a UI setting.

1. Identify the database recovery point and every evidence object inventory/backup/replica that may be restored. Record opaque source identifiers and timestamps.
2. Fetch the latest independently protected checkpoint and verify its signature, monotonic sequence, and journal integrity. If the checkpoint is unavailable, stale beyond policy, inconsistent, or unverifiable, stop; do not substitute the restored database's event count or timestamp.
3. Replay every intent that could post-date any selected database or object recovery point. Replaying the full retained journal is acceptable when idempotent; otherwise the high-watermark proof must show that no relevant event was skipped.
4. Purge exact object generations, plus policy-covered versions, replicas, snapshots, thumbnails, and exports. A storage timeout or ambiguous result remains unresolved and blocks access.
5. For rows present in the restored database, reapply pending/deleted state and audit linkage. If a row is absent, purge the object without recreating the business row. Reconcile unrelated orphan objects against a trusted object manifest before enabling evidence.
6. Verify that the replayed cursor equals the protected checkpoint (or the approved restore barrier), all intents have a terminal state or explicitly approved retained-until date, and exact object-version inventory shows no accessible copy that should be deleted.
7. Produce a signed/minimized reconciliation manifest containing database and object recovery identifiers, checkpoint sequence/hash, intent and completion counts, purge verification counts, unresolved failures, tool version, and timestamps. It must contain no evidence content or credentials.
8. Re-enable evidence access only after the gate is satisfied and an authorized operator records approval. Any unresolved event, unsupported replica/backup path, or purge blocked by retention keeps access disabled.

## Required restore rehearsal matrix

| Scenario | Expected result |
|---|---|
| Database and object restore both predate a later deletion; journal/checkpoint are current | Replay purges all referenced versions, repairs rows where present, and reaches the protected checkpoint. |
| Restored row is absent but a restored object version remains | Purge the exact object and do not recreate the missing claim/evidence record. |
| Database row is restored as accepted while the deletion intent exists | Mark it inaccessible before purge, finish replay, and leave it deleted. |
| Crash after intent, before object deletion | Retry the same intent idempotently and complete the purge. |
| Crash after object purge, before completion acknowledgement | Verify provider state, record completion idempotently, and keep the row inaccessible until finalization. |
| Ledger write unavailable before deletion | Do not purge or report success; leave pending state, alert, and retry. |
| Ledger/checkpoint missing, rolled back, corrupted, reordered, or signature-invalid | Stop replay and keep all evidence access disabled. |
| Delete marker exists but an older version, replica, soft-deleted copy, or locked version remains | Report incomplete purge; keep access disabled until purged or approved retention expiry is proven. |
| Purge request times out or provider result is ambiguous | Re-query exact versions and retry; do not assume success. |
| Object exists without a matching row or deletion intent | Quarantine from access and reconcile against a trusted manifest; never silently expose or bulk-delete it. |
| Concurrent delete/replay workers and duplicate event delivery | Single logical deletion per exact generation; sequence/checkpoint remains monotonic and verifiable. |

The rehearsal must assert denial of every evidence route before and during replay, and after any injected failure. Evidence must not be re-enabled solely because Django checks pass or the main database is healthy.

## Decisions still open

- Provider, region, residency, account/project/subscription boundary, and deployment remain unselected; deployment is deferred.
- Ledger service, checkpoint/signing mechanism, backup policy, recovery identity, and alert destination require provider and operations evaluation.
- Object versioning, soft-delete duration, lifecycle, replication, immutable retention, exact-generation purge, and permanent-deletion observability must be verified for the selected storage service.
- Customer retention periods, legal holds, backup deletion disclosures, and minimum ledger metadata retention require qualified review; no duration is set here.
- Internal-alpha RPO/RTO are planning assumptions only. A production ledger must not be accepted until hosted recovery meets the separately approved objectives and produces rehearsal evidence.

## Completion gate before real evidence

Real evidence remains unsupported until a provider-specific adapter and restore gate pass the matrix above, an independent integrity checkpoint is demonstrated, all recoverable copies and retention interactions are accounted for, access controls and monitoring are configured, customer retention/deletion terms are approved, and a hosted restore rehearsal is reviewed. This design task completes no deployment, provider purchase, or live-data test.
