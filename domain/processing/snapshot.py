from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field

from domain.common import DomainModel, utc_now
from domain.events.base import MatchEvent
from domain.insights.candidate import InsightCandidate
from domain.insights.insight import Insight
from domain.match.match import MatchContext
from domain.match.state import MatchState
from domain.metrics.calculators import MetricSnapshot
from domain.metrics.impact import ActionImpact
from domain.patterns.base import Pattern
from domain.processing.state_change import RichStateChange
from domain.sequences.attack import AttackSequence
from domain.sequences.possession import PossessionChain


class ProcessingMetadata(DomainModel):
    event_id: UUID
    sequence_number: int
    processing_started_at: datetime
    processing_completed_at: datetime
    processing_duration_ms: float
    engine_version: str = "2.0.0"
    schema_version: str = "2.0"
    configuration_version: str = "intelligence.v2"


class ProcessingTelemetry(DomainModel):
    events_processed: int = 0
    processing_duration_ms: float = 0.0
    patterns_evaluated: int = 0
    patterns_detected: int = 0
    candidates_created: int = 0
    candidates_suppressed: int = 0
    insights_validated: int = 0
    insights_rejected: int = 0


class ProcessingTraceStep(DomainModel):
    step: str
    status: str
    detail: str
    event_ids: list[UUID] = Field(default_factory=list)


class ProcessingTrace(DomainModel):
    trace_id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    insight_id: UUID | None = None
    steps: list[ProcessingTraceStep] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class ProcessingSnapshot(DomainModel):
    snapshot_id: UUID = Field(default_factory=uuid4)
    event: MatchEvent
    match_context: MatchContext
    active_possession: PossessionChain | None
    recent_sequences: list[AttackSequence] = Field(default_factory=list)
    metrics: MetricSnapshot
    action_impacts: list[ActionImpact] = Field(default_factory=list)
    match_state: MatchState | None
    state_changes: list[RichStateChange] = Field(default_factory=list)
    patterns: list[Pattern] = Field(default_factory=list)
    candidates: list[InsightCandidate] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    processing_metadata: ProcessingMetadata
