from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import Field

from domain.common import DomainModel, MatchClock
from domain.insights.evidence import EvidenceRef


class RichStateChange(DomainModel):
    change_id: UUID = Field(default_factory=uuid4)
    timestamp: MatchClock
    team_id: UUID
    dimension: str
    before: float
    after: float
    delta: float
    relative_change: float
    significance: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)

