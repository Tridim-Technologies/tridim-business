"""Local, synthetic-data-only journal for expense-evidence deletion intents.

This SQLite-backed journal is separate from the application database and local
evidence directory. It is a development adapter for restore rehearsals, not a
production deletion ledger or a substitute for an independently managed store.
"""

import hashlib
import json
import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings


class DeletionLedgerError(Exception):
    """The local deletion journal cannot safely acknowledge or replay events."""


_ZERO_HASH = "0" * 64
_STORAGE_KEY_RE = re.compile(r"[0-9a-f]{32}\Z")


class LocalSyntheticEvidenceDeletionLedger:
    """Append-only, hash-linked journal for local synthetic evidence deletes."""

    def __init__(self, root=None):
        self.root = Path(root or settings.EXPENSE_EVIDENCE_LEDGER_ROOT).expanduser()
        self.database = self.root / "ledger.sqlite3"

    def _paths(self):
        if not settings.DEBUG or not settings.EXPENSE_EVIDENCE_LOCAL_HOSTS_ALLOWED:
            raise DeletionLedgerError(
                "The local evidence deletion journal is limited to local DEBUG use."
            )
        if not self.root.is_absolute() or self.root.is_symlink():
            raise DeletionLedgerError("The deletion journal path is unsafe.")
        root = self.root.resolve()
        if root == Path(root.anchor) or root == Path(settings.BASE_DIR).resolve():
            raise DeletionLedgerError("The deletion journal path is unsafe.")
        base = Path(settings.BASE_DIR).resolve()
        forbidden = (base / "backend", base / "frontend", base / "static")
        if any(root == path or path in root.parents for path in forbidden):
            raise DeletionLedgerError(
                "The deletion journal cannot be under an application or public directory."
            )

        storage = Path(settings.EXPENSE_EVIDENCE_STORAGE_ROOT).expanduser()
        if not storage.is_absolute():
            raise DeletionLedgerError("Private evidence storage path must be absolute.")
        storage = storage.resolve()
        if root == storage or root in storage.parents or storage in root.parents:
            raise DeletionLedgerError(
                "The deletion journal and evidence storage must use separate directories."
            )

        database = settings.DATABASES["default"]
        if database["ENGINE"].endswith("sqlite3"):
            database_name = database["NAME"]
            if database_name != ":memory:":
                database_path = Path(database_name).expanduser().resolve()
                if (
                    database_path == (root / "ledger.sqlite3").resolve()
                    or root in database_path.parents
                ):
                    raise DeletionLedgerError(
                        "The deletion journal must be separate from the application database."
                    )
        return root

    def _prepare(self, *, create):
        root = self._paths()
        database = root / "ledger.sqlite3"
        if not root.exists():
            if not create:
                return None
            root.mkdir(parents=True, mode=0o700)
            os.chmod(root, 0o700)
        elif not root.is_dir() or root.stat().st_mode & 0o077:
            raise DeletionLedgerError(
                "The deletion journal directory must be private (mode 0700)."
            )

        if database.is_symlink():
            raise DeletionLedgerError("The deletion journal file is unsafe.")
        if not database.exists():
            if not create:
                return None
            descriptor = os.open(
                database,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            os.close(descriptor)
        elif database.stat().st_mode & 0o077:
            raise DeletionLedgerError(
                "The deletion journal file must be private (mode 0600)."
            )
        return database

    def _connect(self, *, create):
        database = self._prepare(create=create)
        if database is None:
            return None
        try:
            connection = sqlite3.connect(database, timeout=10, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA foreign_keys=ON")
            if create:
                self._initialize(connection)
            return connection
        except (OSError, sqlite3.Error) as error:
            raise DeletionLedgerError(
                "The deletion journal is unavailable or corrupt."
            ) from error

    @staticmethod
    def _initialize(connection):
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS deletion_event (
                sequence INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL,
                event_type TEXT NOT NULL CHECK (event_type IN ('intent', 'purged')),
                evidence_id TEXT NOT NULL,
                organization_id TEXT NOT NULL,
                claim_id TEXT NOT NULL,
                storage_key TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                UNIQUE (event_id, event_type)
            );
            CREATE TABLE IF NOT EXISTS ledger_checkpoint (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                sequence INTEGER NOT NULL,
                event_hash TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS deletion_event_no_update
            BEFORE UPDATE ON deletion_event
            BEGIN SELECT RAISE(ABORT, 'deletion events are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS deletion_event_no_delete
            BEFORE DELETE ON deletion_event
            BEGIN SELECT RAISE(ABORT, 'deletion events are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS checkpoint_step_forward
            BEFORE UPDATE ON ledger_checkpoint
            WHEN NEW.sequence != OLD.sequence + 1
            BEGIN SELECT RAISE(ABORT, 'checkpoint must advance by one event'); END;
            CREATE TRIGGER IF NOT EXISTS checkpoint_no_delete
            BEFORE DELETE ON ledger_checkpoint
            BEGIN SELECT RAISE(ABORT, 'checkpoint cannot be deleted'); END;
            """
        )
        connection.execute(
            "INSERT OR IGNORE INTO ledger_checkpoint(singleton, sequence, event_hash) "
            "VALUES (1, 0, ?)",
            (_ZERO_HASH,),
        )

    @staticmethod
    def _payload(row):
        return {
            "sequence": row["sequence"],
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "evidence_id": row["evidence_id"],
            "organization_id": row["organization_id"],
            "claim_id": row["claim_id"],
            "storage_key": row["storage_key"],
            "reason_code": row["reason_code"],
            "recorded_at": row["recorded_at"],
            "previous_hash": row["previous_hash"],
        }

    @classmethod
    def _event_hash(cls, row):
        body = json.dumps(
            cls._payload(row), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(body).hexdigest()

    def _verified_events(self, connection):
        try:
            checkpoint = connection.execute(
                "SELECT sequence, event_hash FROM ledger_checkpoint WHERE singleton=1"
            ).fetchone()
            if checkpoint is None:
                raise DeletionLedgerError("Deletion journal checkpoint is missing.")
            rows = connection.execute(
                "SELECT * FROM deletion_event ORDER BY sequence"
            ).fetchall()
        except sqlite3.Error as error:
            raise DeletionLedgerError("Deletion journal is corrupt.") from error

        previous_hash = _ZERO_HASH
        events = []
        intents = {}
        completed = set()
        for expected_sequence, row in enumerate(rows, start=1):
            if (
                row["sequence"] != expected_sequence
                or row["previous_hash"] != previous_hash
                or row["event_hash"] != self._event_hash(row)
                or not _STORAGE_KEY_RE.fullmatch(row["storage_key"])
            ):
                raise DeletionLedgerError(
                    "Deletion journal integrity verification failed."
                )
            if row["event_type"] == "intent":
                if row["event_id"] in intents:
                    raise DeletionLedgerError("Deletion journal has duplicate intents.")
                intents[row["event_id"]] = row
            elif row["event_id"] not in intents:
                raise DeletionLedgerError(
                    "Deletion journal has a completion without an intent."
                )
            else:
                intent = intents[row["event_id"]]
                for field in (
                    "evidence_id",
                    "organization_id",
                    "claim_id",
                    "storage_key",
                ):
                    if row[field] != intent[field]:
                        raise DeletionLedgerError(
                            "Deletion journal completion does not match its intent."
                        )
                if row["event_id"] in completed:
                    raise DeletionLedgerError(
                        "Deletion journal has duplicate purge completions."
                    )
                completed.add(row["event_id"])
            events.append(dict(row))
            previous_hash = row["event_hash"]

        if (
            checkpoint["sequence"] != len(events)
            or checkpoint["event_hash"] != previous_hash
        ):
            raise DeletionLedgerError(
                "Deletion journal checkpoint does not match its event history."
            )
        return events

    @staticmethod
    def _metadata(evidence_id, organization_id, claim_id, storage_key, reason_code):
        storage_key = str(storage_key)
        if not _STORAGE_KEY_RE.fullmatch(storage_key):
            raise DeletionLedgerError("Invalid private evidence object reference.")
        return {
            "event_id": str(evidence_id),
            "evidence_id": str(evidence_id),
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "storage_key": storage_key,
            "reason_code": reason_code[:40],
        }

    def _append(self, event_type, metadata):
        connection = self._connect(create=True)
        try:
            connection.execute("BEGIN IMMEDIATE")
            events = self._verified_events(connection)
            previous = events[-1]["event_hash"] if events else _ZERO_HASH
            prior = next(
                (
                    event
                    for event in events
                    if event["event_id"] == metadata["event_id"]
                    and event["event_type"] == event_type
                ),
                None,
            )
            if prior:
                for field in (
                    "evidence_id",
                    "organization_id",
                    "claim_id",
                    "storage_key",
                ):
                    if prior[field] != metadata[field]:
                        raise DeletionLedgerError(
                            "Deletion retry does not match its original intent."
                        )
                connection.execute("COMMIT")
                return dict(prior)
            if event_type == "purged" and not any(
                event["event_id"] == metadata["event_id"]
                and event["event_type"] == "intent"
                for event in events
            ):
                raise DeletionLedgerError(
                    "Cannot record purge completion without a durable intent."
                )

            payload = {
                "sequence": len(events) + 1,
                **metadata,
                "event_type": event_type,
                "recorded_at": datetime.now(UTC).isoformat(),
                "previous_hash": previous,
            }
            payload["event_hash"] = self._event_hash(payload)
            connection.execute(
                "INSERT INTO deletion_event("
                + ",".join(payload)
                + ") VALUES ("
                + ",".join("?" for _ in payload)
                + ")",
                tuple(payload.values()),
            )
            connection.execute(
                "UPDATE ledger_checkpoint SET sequence=?, event_hash=? WHERE singleton=1",
                (payload["sequence"], payload["event_hash"]),
            )
            connection.execute("COMMIT")
            return payload
        except DeletionLedgerError:
            if connection is not None and connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        except sqlite3.Error as error:
            if connection is not None and connection.in_transaction:
                connection.execute("ROLLBACK")
            raise DeletionLedgerError(
                "Could not durably write to the deletion journal."
            ) from error
        finally:
            connection.close()

    def record_intent(
        self, evidence_id, organization_id, claim_id, storage_key, reason_code
    ):
        return self._append(
            "intent",
            self._metadata(
                evidence_id, organization_id, claim_id, storage_key, reason_code
            ),
        )

    def record_purged(
        self, evidence_id, organization_id, claim_id, storage_key, reason_code
    ):
        return self._append(
            "purged",
            self._metadata(
                evidence_id, organization_id, claim_id, storage_key, reason_code
            ),
        )

    def intents(self):
        connection = self._connect(create=False)
        if connection is None:
            return []
        try:
            events = self._verified_events(connection)
        finally:
            connection.close()
        completed = {
            event["event_id"] for event in events if event["event_type"] == "purged"
        }
        return [
            {**event, "purged": event["event_id"] in completed}
            for event in events
            if event["event_type"] == "intent"
        ]
