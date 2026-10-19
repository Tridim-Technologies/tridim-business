# Synthetic expense claims in the internal alpha

**Status:** Software workflow for synthetic records only

The Expenses screen lets an assigned organization member create one draft per expense and submit it for review. Each claim is linked to a job. A gated local upload path can accept synthetic JPEG, PNG, and PDF evidence after server validation and a clean ClamAV scan. It is disabled by default and must never be used with real expense information or files. When disabled or unavailable, a claimant explains why the receipt is missing and a different authorized reviewer must record a reasoned waiver before approval.

The [MVP workflow](EXPENSE_CLAIM_MVP_WORKFLOW.md) defines the product rules. [ADR-005](ADR-005-EXPENSE-EVIDENCE-HANDLING.md) defines the safeguards; production storage/scanning, access-auditing review, retention, backup, deletion, and real-data use remain gated.

## Use the screen

1. Sign in to an organization and open **Expenses**. An active job assignment is required to create or submit a draft. A cancelled job cannot receive a new claim.
2. Enter the expense date, exact amount, three-letter uppercase currency, category, business purpose, and optional merchant. Attach a synthetic receipt if the development upload path is enabled, or enter a missing-receipt explanation before submitting. Drafts can be edited.
3. Submit the draft. An owner, admin, or operations member other than the claimant may return it with a reason, reject it with a reason, record a reasoned waiver when evidence is missing, or approve it when the current version has accepted evidence or a waiver.
4. Edit a returned claim before resubmitting it as a new version. The prior submitted snapshot and review history remain visible. A waiver from an earlier version does not carry over.
5. The claimant may withdraw a draft, submitted, or returned claim. Approval, rejection, and withdrawal are terminal in this alpha.

Claimants retain their own claim history after job unassignment while they remain organization members. Reviewers can see organization claims and evidence. Finance members see approved claim metadata for other people, without reasons, history, or evidence access. A finance member who is also the claimant retains access to their own claim and evidence. Existing support grants do not provide claim access.

## Local synthetic receipt evidence

The local walkthrough uses these tools:

- The **official ClamAV universal macOS package** installs the scanner on Intel and Apple Silicon. **Homebrew** is an alternative package manager.
- **ClamAV** provides `freshclam` to download/update malware definitions and `clamd` to scan uploads over a Unix socket.
- **GnuPG (`gpg`)** verifies the downloaded package signature; macOS's built-in `installer` installs the verified PKG.
- **uv + Python 3.12** run the Django backend; **Node.js + npm/Vite** run the React frontend. The project README lists the supported development versions and start commands.

See the [official ClamAV macOS installation instructions](https://docs.clamav.net/manual/Installing.html#macos), [release downloads](https://www.clamav.net/download.html), and the [ClamAV configuration guide](https://docs.clamav.net/manual/Usage/Configuration.html) for installation-specific details.

The evidence route is available only when Django is running with `DEBUG=1` and `EXPENSE_EVIDENCE_ENABLED=1`. Keep it disabled for normal work. It uses a private local directory outside static/media serving, defaulting to `.private-evidence/` in the repository root, and a local ClamAV daemon exposed through a Unix socket. Deletion events go to a distinct private journal directory, defaulting to `.private-evidence-ledger/`; configure it with `EXPENSE_EVIDENCE_LEDGER_ROOT` if needed. Keep this journal outside any database/evidence snapshot used to rehearse a restore. The local journal is not a production recovery service. Set `EXPENSE_EVIDENCE_CLAMD_SOCKET` to the scanner socket path. The application does not install or start ClamAV.

### macOS developer setup

Download the current **macOS universal PKG**, its matching `.sig` file, and the Cisco Talos public key linked from the official ClamAV download page. Verify the package signature before installing. The PKG installs under `/usr/local/clamav`; macOS will request administrator authentication for installation. It includes sample configuration files, but does not configure the scanner or database for you.

```sh
gpg --import cisco-talos.gpg
gpg --verify clamav-X.Y.Z.macos.universal.pkg.sig clamav-X.Y.Z.macos.universal.pkg
sudo installer -pkg clamav-X.Y.Z.macos.universal.pkg -target /
export PATH="/usr/local/clamav/bin:/usr/local/clamav/sbin:$PATH"
CLAMAV_ETC="$HOME/.config/clamav"
CLAMAV_DATA="$HOME/.local/share/clamav"
CLAMAV_RUN="$HOME/.local/run/clamav"
mkdir -p "$CLAMAV_ETC" "$CLAMAV_DATA" "$CLAMAV_RUN"
chmod 700 "$CLAMAV_ETC" "$CLAMAV_DATA" "$CLAMAV_RUN"
cp /usr/local/clamav/etc/freshclam.conf.sample "$CLAMAV_ETC/freshclam.conf"
cp /usr/local/clamav/etc/clamd.conf.sample "$CLAMAV_ETC/clamd.conf"
```

In both configuration files, remove or comment out the `Example` line. In both files, set `DatabaseDirectory` to the absolute path in `$CLAMAV_DATA`. In `clamd.conf`, set `LocalSocket` to the absolute path in `$CLAMAV_RUN` followed by `/clamd.sock`, and set `LocalSocketMode 600`. Download definitions, then start ClamAV in a terminal:

```sh
freshclam --config-file "$CLAMAV_ETC/freshclam.conf"
clamd --config-file "$CLAMAV_ETC/clamd.conf" --foreground
```

In a second terminal, set the same `CLAMAV_RUN` path and start the backend with the local feature gate and socket path. Leave `DJANGO_DEBUG=1` and `DJANGO_ALLOWED_HOSTS` restricted to `localhost,127.0.0.1` (the development defaults). Do not put secrets or real receipt data in this walkthrough.

```sh
CLAMAV_RUN="$HOME/.local/run/clamav"
EXPENSE_EVIDENCE_ENABLED=1 \
EXPENSE_EVIDENCE_CLAMD_SOCKET="$CLAMAV_RUN/clamd.sock" \
uv run python backend/manage.py runserver 127.0.0.1:8000
```

Homebrew is also supported; follow the [official ClamAV package instructions](https://docs.clamav.net/manual/Installing/Packages.html) for its configuration paths. On some macOS/Intel setups, Homebrew builds large dependencies from source and needs substantial temporary disk space, so check `df -h /` first.

In a third terminal, run the frontend:

```sh
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Use a newly generated JPEG, PNG, or PDF containing synthetic information only. Confirm it appears as accepted, download it as an attachment, then remove it while the claim is still editable. Stop both development servers and `clamd` with Ctrl+C. Without a configured scanner, after a scanner timeout, or after an invalid scan response, the upload stays quarantined and cannot be downloaded.

Use a disposable local database for the walkthrough, and keep its evidence storage and journal under separate private directories by setting `DATABASE_URL`, `EXPENSE_EVIDENCE_STORAGE_ROOT`, and `EXPENSE_EVIDENCE_LEDGER_ROOT` for the backend. Do not point this workflow at a database, evidence directory, or journal containing real or otherwise valuable local data. After stopping the services, remove only the temporary database and directories you created for the walkthrough; leave your normal development database, `.private-evidence/`, and `.private-evidence-ledger/` alone. The `cleanup_expense_evidence` management command separately handles stale quarantined/rejected files and retries journaled deletions.

Only use generated synthetic files. Current limits are 10 MiB per file, five files per claim version, and 25 MiB across a claim. The backend checks the extension, declared MIME type, file signature, image decoding/dimensions, PDF parsing/encryption/page count, and SHA-256 digest. Originals are stored under opaque names with directory mode `0700` and file mode `0600`; download requires a fresh organization/claim/role check and is sent as an attachment with `nosniff`. A draft claimant may remove evidence. Submitted evidence remains attached to its version; evidence added after return belongs to the next version.

The `cleanup_expense_evidence` command journals and purges stale quarantined/rejected files and retries pending, deleted, and journaled object deletions. To review which accepted synthetic files an explicit cutoff would expire, run a dry run:

```sh
DJANGO_DEBUG=1 EXPENSE_EVIDENCE_ENABLED=1 uv run python backend/manage.py expire_expense_evidence \
  --accepted-before "<timezone-aware ISO 8601 cutoff>"
```

The command requires a past, timezone-aware cutoff and has no default retention duration. It reports only the number and total size of matching accepted evidence. To apply a reviewed synthetic-data cleanup, add `--apply --reason "<brief non-sensitive reason>"`. The command records the supplied cutoff and reason in the evidence audit metadata, makes the row inaccessible before writing a journal intent and removing file bytes, and leaves failed removals retryable. Keep reasons short; do not include receipt details or other personal data. This operation is limited to the local synthetic-data gate and does not set an organization retention policy.

For a local synthetic restore, keep the backend stopped and leave `EXPENSE_EVIDENCE_ENABLED` unset or `0`. Ensure `.private-evidence-ledger/` contains the journal newer than the database and evidence-directory snapshots, then run a dry run and apply the replay:

```sh
DJANGO_DEBUG=1 uv run python backend/manage.py reconcile_expense_evidence_deletions
DJANGO_DEBUG=1 uv run python backend/manage.py reconcile_expense_evidence_deletions --apply
```

The command checks journal integrity, purges restored bytes for every recorded deletion, repairs matching rows, and handles pending/deleted rows without an intent. Then, while the backend remains stopped, run `cleanup_expense_evidence` with `EXPENSE_EVIDENCE_ENABLED=1` to clean any stale quarantine/rejection objects. The local journal helps rehearse restores only when preserved; it can itself be rolled back or lost. A database and evidence snapshot from before a deletion cannot be reconciled if the journal also lacks that intent. The provider-neutral production requirements are in [ADR-005](ADR-005-EXPENSE-EVIDENCE-HANDLING.md#independent-deletion-ledger-design). Real evidence remains unsupported until an independent production ledger and storage-specific restore reconciliation are implemented and verified.

Approval does not create an invoice line, ledger entry, reimbursement, payroll item, or payment. Currencies stay separate.

## API contract

All routes require an authenticated session and organization membership. JSON writes require the session CSRF token.

| Route | Method | Purpose |
|---|---|---|
| `/api/organizations/{organization_id}/expense-claims/` | GET | List claims within the caller's role scope. |
| Same route | POST | Create a draft. Supply `job_id`, `expense_date`, `amount` as a decimal string, `currency`, `category`, `purpose`, and optional `merchant` and `missing_receipt_explanation`. |
| `/api/organizations/{organization_id}/expense-claims/{claim_id}/` | GET | Read a claim within the caller's role scope. |
| Same route | PATCH | Edit only a claimant-owned draft or returned claim. Supply changed claim fields and the current `revision`; job, organization, claimant, and receipt state cannot be changed. |
| `/api/organizations/{organization_id}/expense-claims/{claim_id}/transition/` | POST | Supply `action`, current `revision`, and `reason` where required. Actions: `submit`, `return`, `resubmit`, `waive`, `approve`, `reject`, `withdraw`. |
| `/api/organizations/{organization_id}/expense-claims/{claim_id}/evidence/` | GET, POST | List evidence or upload a multipart `file` and current `revision`; upload requires the development gate and a clean scan. |
| `/api/organizations/{organization_id}/expense-claims/{claim_id}/evidence/{evidence_id}/` | GET, DELETE | Download accepted evidence as an attachment or remove it from an editable draft/returned version. |

For example, a synthetic transition body is:

```json
{"action":"waive","revision":2,"reason":"Synthetic exception approved for workflow check"}
```

The API increments `revision` after each successful claim mutation. A stale revision returns HTTP 409; refresh the claim before retrying. The `version` field identifies the submitted claim snapshot and increments on resubmission. History records the actor, time, reason, status, version, and claim fields for each action. Client-supplied receipt or waiver flags are rejected. The server derives `receipt_state` as `missing`, `accepted`, or `waived` for the current submitted version. The evidence list shows earlier versions as immutable history.

The API returns 404 for claims/evidence outside the caller's organization or action scope, 400 for invalid fields, and 409 for a stale revision or invalid status transition. Uploads use the same session cookie and CSRF token as other writes; the browser must send `multipart/form-data` without setting the `Content-Type` header manually.

## Implementation boundary

This gated synthetic increment adds an upload endpoint, local private storage, validation, quarantine/scanning, role checks, access audit events, safe downloads, and bounded cleanup. Real receipt and expense data remain blocked until the remaining controls and open decisions in ADR-005 are implemented and verified.
