from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import Field

from domain.common import DomainModel, MatchClock
from domain.enums import AttackOrigin, TagCode
from domain.insights.evidence import EvidenceRef


class AttackSequence(DomainModel):
    sequence_id: UUID = Field(default_factory=uuid4)
    match_id: UUID
    team_id: UUID
    start_time: MatchClock
    end_time: MatchClock | None = None
    possession_ids: list[UUID] = Field(default_factory=list)
    event_ids: list[UUID] = Field(default_factory=list)
    origin: AttackOrigin = AttackOrigin.OPEN_PLAY
    progression: float = 0.0
    spatial_pattern: str | None = None
    chance_created: bool = False
    shot_created: bool = False
    goal_created: bool = False
    outcome: str = "IN_PROGRESS"
    reason_codes: list[TagCode] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)

