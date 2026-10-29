from __future__ import annotations

from typing import Dict
from uuid import UUID

from services.repositories.match_state import MatchStateRecord, MatchStateRepository


class LocalLoggingMatchStateRepository(MatchStateRepository):
    """A tiny local repository used for smoke tests and local runs.

    It stores MatchStateRecord objects in memory and logs saves. This is
    intentionally lightweight and should NOT be used in production.
    """

    def __init__(self) -> None:
        self._store: Dict[UUID, MatchStateRecord] = {}

    def get(self, match_id: UUID) -> MatchStateRecord | None:
        return self._store.get(match_id)

    def save(self, record: MatchStateRecord, expected_version: int | None = None) -> MatchStateRecord:
        # simple optimistic version check for smoke tests
        existing = self._store.get(record.match_id)
        if expected_version is not None and existing is not None and existing.version != expected_version:
            raise RuntimeError("version conflict")
        # increment version
        record.version = (existing.version + 1) if existing is not None else 1
        self._store[record.match_id] = record
        return record
