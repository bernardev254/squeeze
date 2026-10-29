from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import Field

from domain.common import DomainModel, utc_now


class DeadLetterRecord(DomainModel):
    dead_letter_id: UUID = Field(default_factory=uuid4)
    event_id: UUID | None = None
    match_id: UUID | None = None
    failure_reason: str
    error_type: str
    attempt_count: int = 1
    timestamp: datetime = Field(default_factory=utc_now)
    original_payload_reference: str


class DeadLetterSink(Protocol):
    def record(self, record: DeadLetterRecord) -> None:
        ...

# InMemoryDeadLetterSink removed — use cloud-backed implementations only.
