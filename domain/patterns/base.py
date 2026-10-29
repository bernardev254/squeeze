from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import Field

from domain.common import DomainModel, MatchClock, TimeWindow
from domain.enums import CausalFactorType, ConsequenceType, PatternType
from domain.insights.evidence import EvidenceRef


class CausalFactor(DomainModel):
    factor_type: CausalFactorType
    event_ids: list[UUID] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class Consequence(DomainModel):
    consequence_type: ConsequenceType
    event_ids: list[UUID] = Field(default_factory=list)
    value: float | None = None


class Pattern(DomainModel):
    pattern_id: UUID = Field(default_factory=uuid4)
    match_id: UUID
    pattern_type: PatternType
    team_id: UUID
    player_id: UUID | None = None
    detected_at: MatchClock
    observation_window: TimeWindow
    confidence: float = Field(ge=0.0, le=1.0)
    significance: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceRef]
    causes: list[CausalFactor] = Field(default_factory=list)
    consequences: list[Consequence] = Field(default_factory=list)
    state_before: dict[str, float] = Field(default_factory=dict)
    state_after: dict[str, float] = Field(default_factory=dict)
    deduplication_key: str

