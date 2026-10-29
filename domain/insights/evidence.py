from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import Field

from domain.common import DomainModel


class EvidenceRef(DomainModel):
    evidence_id: UUID = Field(default_factory=uuid4)
    source_type: str
    event_ids: list[UUID] = Field(default_factory=list)
    impact_ids: list[UUID] = Field(default_factory=list)
    metric: str
    value: float | str
    baseline: float | str | None = None
    time_window: str
    explanation: str
