from __future__ import annotations

from uuid import UUID

from pydantic import Field

from domain.causal.model import CausalChain
from domain.common import DomainModel
from domain.enums import Audience
from domain.events.base import MatchEvent
from domain.insights.claim import InsightClaim
from domain.insights.evidence import EvidenceRef
from domain.insights.insight import Insight
from domain.match.match import MatchContext
from domain.match.state import MatchState
from domain.metrics.calculators import MetricSnapshot
from domain.metrics.impact import ActionImpact
from domain.patterns.base import Pattern
from domain.sequences.attack import AttackSequence


class AnalystContext(DomainModel):
    match: MatchContext
    current_state: MatchState | None
    pattern_candidate: Pattern
    evidence: list[EvidenceRef]
    action_impacts: list[ActionImpact] = Field(default_factory=list, max_length=8)
    causal_chain: CausalChain | None
    recent_events: list[MatchEvent] = Field(max_length=8)
    relevant_sequences: list[AttackSequence] = Field(default_factory=list)


class ExplanationContext(DomainModel):
    match: MatchContext
    validated_pattern: Pattern
    evidence: list[EvidenceRef]
    action_impacts: list[ActionImpact] = Field(default_factory=list, max_length=8)
    causal_chain: CausalChain | None
    consequences: list[str]


class ValidatorContext(DomainModel):
    claim: InsightClaim
    evidence: list[EvidenceRef]
    underlying_events: list[MatchEvent] = Field(max_length=12)
    action_impacts: list[ActionImpact] = Field(default_factory=list, max_length=12)
    metrics: MetricSnapshot
    pattern: Pattern
    causal_chain: CausalChain | None


class NarrativeContext(DomainModel):
    insight: Insight
    audience: Audience
    tone: str = "clear"
    length_constraints: str = "short"
    available_evidence: list[EvidenceRef]


class PersonalizationContext(DomainModel):
    insight_id: UUID
    audience: Audience
    user_segment: str
    allowed_claim_ids: list[UUID] = Field(default_factory=list)
