"""Structural contracts for local synthetic evidence adapters.

These interfaces make deletion orchestration replaceable in tests. They do not
select or certify a production storage or recovery provider.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class EvidenceStorage(Protocol):
    """Private byte storage operations used by evidence workflows."""

    def put(self, content: bytes) -> str: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...


@runtime_checkable
class EvidenceDeletionJournal(Protocol):
    """Durable, idempotent deletion-intent journal operations."""

    def record_intent(
        self,
        evidence_id,
        organization_id,
        claim_id,
        storage_key: str,
        reason_code: str,
    ): ...

    def record_purged(
        self,
        evidence_id,
        organization_id,
        claim_id,
        storage_key: str,
        reason_code: str,
    ): ...

    def intents(self) -> list[dict]: ...
