from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import Field

from domain.common import DomainModel, MatchClock, TimeWindow
from domain.enums import Audience, ConsequenceType, InsightStatus, InsightType
from domain.insights.evidence import EvidenceRef


class Insight(DomainModel):
    insight_id: UUID = Field(default_factory=uuid4)
    match_id: UUID
    insight_type: InsightType
    detected_at: MatchClock
    team_id: UUID
    player_id: UUID | None = None
    importance: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    observation_window: TimeWindow
    pattern_id: UUID
    candidate_id: UUID | None = None
    claim_id: UUID | None = None
    validation_id: UUID | None = None
    causal_chain_id: UUID | None = None
    trace_id: UUID | None = None
    evidence: list[EvidenceRef]
    claim: str
    explanation: str
    consequences: list[ConsequenceType] = Field(default_factory=list)
    audiences: list[Audience] = Field(default_factory=lambda: list(Audience))
    status: InsightStatus = InsightStatus.DETECTED
    pattern_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    claim_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    validation_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    available_at: MatchClock | None = None
    expires_at: MatchClock | None = None


class FanRepresentation(DomainModel):
    text: str


class CommentatorRepresentation(DomainModel):
    text: str


class StudioRepresentation(DomainModel):
    headline: str
    lines: list[str]


class OverlayRepresentation(DomainModel):
    headline: str
    stat: str


class AudienceRepresentations(DomainModel):
    fan: FanRepresentation
    commentator: CommentatorRepresentation
    studio: StudioRepresentation
    overlay: OverlayRepresentation
