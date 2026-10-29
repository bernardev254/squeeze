from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field

from domain.common import DomainModel, TimeWindow, utc_now
from domain.enums import ClaimType, PatternType
from domain.insights.evidence import EvidenceRef


class InsightClaim(DomainModel):
    claim_id: UUID = Field(default_factory=uuid4)
    claim_type: ClaimType
    subject_team_id: UUID
    subject_player_id: UUID | None = None
    predicate: str
    object: dict[str, float | str | int | None]
    pattern_id: UUID
    pattern_type: PatternType
    evidence: list[EvidenceRef]
    observation_window: TimeWindow
    created_at: datetime = Field(default_factory=utc_now)
    claim_confidence: float = Field(ge=0.0, le=1.0)

