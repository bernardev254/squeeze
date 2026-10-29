from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import Field

from domain.common import DomainModel, MatchClock
from domain.enums import CausalFactorType, ConsequenceType, PatternType


class CausalStep(DomainModel):
    label: str
    factor_type: CausalFactorType | None = None
    consequence_type: ConsequenceType | None = None
    event_ids: list[UUID] = Field(default_factory=list)
    sequence_ids: list[UUID] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)


class Impact(DomainModel):
    description: str
    magnitude: float = Field(ge=0.0, le=1.0)
    metric: str | None = None
    value: float | None = None


class CausalChain(DomainModel):
    chain_id: UUID = Field(default_factory=uuid4)
    pattern_id: UUID
    match_id: UUID
    team_id: UUID
    pattern_type: PatternType
    created_at: MatchClock
    steps: list[CausalStep]
    impacts: list[Impact] = Field(default_factory=list)

