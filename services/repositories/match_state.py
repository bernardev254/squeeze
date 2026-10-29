from __future__ import annotations

from typing import Protocol
from uuid import UUID

from domain.common import DomainModel
from domain.processing.snapshot import ProcessingSnapshot
from services.match_engine.processor import MatchProcessor


class MatchStateRecord(DomainModel):
    match_id: UUID
    version: int = 0
    processor: MatchProcessor
    latest_snapshot: ProcessingSnapshot | None = None


class MatchStateRepository(Protocol):
    def get(self, match_id: UUID) -> MatchStateRecord | None:
        ...

    def save(self, record: MatchStateRecord, expected_version: int | None = None) -> MatchStateRecord:
        ...


class AzureMatchStateRepository:  # concrete placeholder for future Azure implementation
    """Adapter boundary for Azure persistence.

    Implement a concrete Azure-backed repository here. The previous in-memory
    implementation has been removed to enforce cloud-only operation.
    """
    def __init__(self) -> None:
        raise NotImplementedError("AzureMatchStateRepository is not implemented yet")

