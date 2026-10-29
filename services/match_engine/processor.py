from __future__ import annotations

from time import perf_counter
from uuid import UUID

from pydantic import Field, PrivateAttr

from domain.causal.model import CausalChain, CausalStep, Impact
from domain.common import (
    DomainModel,
    EventTag,
    MatchClock,
    MetricValue,
    StateChange,
    TimeWindow,
    utc_now,
)
from domain.enums import (
    AttackOrigin,
    CausalFactorType,
    ClaimType,
    ConsequenceType,
    EventType,
    InsightStatus,
    PatternType,
    PitchChannel,
    PitchThird,
    PossessionEndReason,
    TagCode,
    TagSource,
)
from domain.events.base import MatchEvent
from domain.events.defensive import DefensiveEvent
from domain.events.offensive import CarryEvent, PassEvent, ShotEvent
from domain.insights.candidate import InsightCandidate
from domain.insights.claim import InsightClaim
from domain.insights.evidence import EvidenceRef
from domain.insights.insight import AudienceRepresentations, Insight
from domain.match.match import MatchContext
from domain.match.state import MatchState
from domain.metrics.calculators import MetricSnapshot, calculate_match_state, calculate_metrics
from domain.metrics.impact import ActionImpact, calculate_action_impact
from domain.patterns.base import CausalFactor, Consequence, Pattern
from domain.processing.snapshot import (
    ProcessingMetadata,
    ProcessingSnapshot,
    ProcessingTelemetry,
    ProcessingTrace,
    ProcessingTraceStep,
)
from domain.processing.state_change import RichStateChange
from domain.sequences.attack import AttackSequence
from domain.sequences.possession import PossessionChain
from domain.sequences.transition import TransitionSequence
from services.insight_engine.explainer import TemplateInsightExplainer
from services.match_engine.config import IntelligenceConfig, load_config
from services.match_engine.errors import DuplicateEvent, InvalidSequence, OutOfOrderEvent
from services.validation.validator import InsightValidator, ValidationResult


class ProcessingResult(DomainModel):
    event: MatchEvent
    possession_created: PossessionChain | None = None
    possession_updated: PossessionChain | None = None
    sequence_updates: list[AttackSequence] = Field(default_factory=list)
    metric_changes: list[MetricValue] = Field(default_factory=list)
    state_change: StateChange | None = None
    state_changes: list[RichStateChange] = Field(default_factory=list)
    patterns_detected: list[Pattern] = Field(default_factory=list)
    causal_chains_created: list[CausalChain] = Field(default_factory=list)
    candidates_created: list[InsightCandidate] = Field(default_factory=list)
    claims_created: list[InsightClaim] = Field(default_factory=list)
    validations_created: list[ValidationResult] = Field(default_factory=list)
    insights_created: list[Insight] = Field(default_factory=list)
    action_impact: ActionImpact | None = None
    snapshot: ProcessingSnapshot | None = None


class MatchProcessor(DomainModel):
    context: MatchContext
    config: IntelligenceConfig = Field(default_factory=load_config)
    events: list[MatchEvent] = Field(default_factory=list)
    possessions: list[PossessionChain] = Field(default_factory=list)
    active_possession: PossessionChain | None = None
    attacks: list[AttackSequence] = Field(default_factory=list)
    transitions: list[TransitionSequence] = Field(default_factory=list)
    action_impacts: list[ActionImpact] = Field(default_factory=list)
    metrics: MetricSnapshot = Field(default_factory=MetricSnapshot)
    state: MatchState | None = None
    patterns: list[Pattern] = Field(default_factory=list)
    causal_chains: list[CausalChain] = Field(default_factory=list)
    candidates: list[InsightCandidate] = Field(default_factory=list)
    claims: list[InsightClaim] = Field(default_factory=list)
    validations: list[ValidationResult] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    representations: dict[UUID, AudienceRepresentations] = Field(default_factory=dict)
    snapshots: list[ProcessingSnapshot] = Field(default_factory=list)
    state_changes: list[RichStateChange] = Field(default_factory=list)
    processing_traces: list[ProcessingTrace] = Field(default_factory=list)
    telemetry: ProcessingTelemetry = Field(default_factory=ProcessingTelemetry)
    _dedupe_seconds: dict[str, int] = PrivateAttr(default_factory=dict)
    _processed_event_ids: set[UUID] = PrivateAttr(default_factory=set)
    _last_sequence: int = PrivateAttr(default=0)
    _last_clock_seconds: int = PrivateAttr(default=0)

    def process_event(self, event: MatchEvent) -> ProcessingResult:
        started_at = utc_now()
        started_perf = perf_counter()
        self._validate_event_ordering(event)
        previous_state = self.state
        event = self._prepare_event(event)
        self.context = self.context.model_copy(
            update={"current_clock": event.match_clock, "period": event.period}
        )
        if event.event_type == EventType.GOAL:
            self.context = self.context.with_score_goal_for(event.team_id)

        possession_created = self._update_possession(event)
        attack = self._update_attack(event)
        transition = self._update_transition(event)
        if transition:
            self.transitions.append(transition)
        self.events.append(event)
        action_impact = calculate_action_impact(self.context, event, previous_state)
        self.action_impacts.append(action_impact)
        self.metrics = calculate_metrics(self.context, self.events, self.possessions, self.transitions, self.action_impacts)
        self.state = calculate_match_state(self.context, self.metrics)
        state_change = self._state_change(previous_state, self.state, event.match_clock)
        rich_changes = self._rich_state_changes(previous_state, self.state, event)
        patterns = self._detect_patterns(event, state_change)
        candidates = [self._candidate_from_pattern(pattern) for pattern in patterns]
        causal_chains = [self._causal_chain_from_pattern(pattern) for pattern in patterns]
        claims = [self._claim_from_pattern(pattern) for pattern in patterns]
        validator = InsightValidator()
        validations = [
            validator.validate(claim, pattern)
            for claim, pattern in zip(claims, patterns, strict=True)
        ]
        explainer = TemplateInsightExplainer()
        insights: list[Insight] = []
        for candidate, pattern, validation, claim, chain in zip(
            candidates,
            patterns,
            validations,
            claims,
            causal_chains,
            strict=True,
        ):
            if not validation.valid:
                continue
            expires_at = self._clock_plus(pattern.detected_at, self.config.insight_ttl_seconds)
            insights.append(
                explainer.explain(candidate, pattern, self.context).model_copy(
                    update={
                        "status": InsightStatus.AVAILABLE,
                        "claim_id": claim.claim_id,
                        "validation_id": validation.validation_id,
                        "causal_chain_id": chain.chain_id,
                        "pattern_confidence": pattern.confidence,
                        "claim_confidence": claim.claim_confidence,
                        "validation_confidence": validation.validation_confidence,
                        "available_at": pattern.detected_at,
                        "expires_at": expires_at,
                    }
                )
            )
        for insight in insights:
            self.representations[insight.insight_id] = explainer.represent(insight, self.context)
        self.patterns.extend(patterns)
        self.causal_chains.extend(causal_chains)
        self.candidates.extend(candidates)
        self.claims.extend(claims)
        self.validations.extend(validations)
        self.insights.extend(insights)
        self.state_changes.extend(rich_changes)
        self._processed_event_ids.add(event.event_id)
        self._last_sequence = event.sequence
        self._last_clock_seconds = event.match_clock.total_seconds()
        self.expire_insights(event.match_clock)
        completed_at = utc_now()
        duration_ms = round((perf_counter() - started_perf) * 1000, 3)
        metadata = ProcessingMetadata(
            event_id=event.event_id,
            sequence_number=event.sequence,
            processing_started_at=started_at,
            processing_completed_at=completed_at,
            processing_duration_ms=duration_ms,
        )
        snapshot = ProcessingSnapshot(
            event=event,
            match_context=self.context,
            active_possession=self.active_possession,
            recent_sequences=self.attacks[-3:],
            metrics=self.metrics,
            action_impacts=self.action_impacts[-8:],
            match_state=self.state,
            state_changes=rich_changes,
            patterns=patterns,
            candidates=candidates,
            insights=insights,
            processing_metadata=metadata,
        )
        self.snapshots.append(snapshot)
        trace = self._trace_for_event(event, action_impact, patterns, candidates, claims, validations, insights)
        for insight in insights:
            insight.trace_id = trace.trace_id
        self.processing_traces.append(trace)
        self._update_telemetry(duration_ms, patterns, candidates, validations, insights)
        return ProcessingResult(
            event=event,
            possession_created=possession_created,
            possession_updated=self.active_possession,
            sequence_updates=[attack] if attack else [],
            metric_changes=self._metric_changes(event),
            state_change=state_change,
            state_changes=rich_changes,
            patterns_detected=patterns,
            causal_chains_created=causal_chains,
            candidates_created=candidates,
            claims_created=claims,
            validations_created=validations,
            insights_created=insights,
            action_impact=action_impact,
            snapshot=snapshot,
        )

    def expire_insights(self, current_clock: MatchClock) -> None:
        for insight in self.insights:
            if insight.status != InsightStatus.AVAILABLE or not insight.expires_at:
                continue
            if current_clock.total_seconds() > insight.expires_at.total_seconds():
                insight.status = InsightStatus.EXPIRED

    def _clock_plus(self, clock: MatchClock, seconds: int) -> MatchClock:
        total = clock.total_seconds() + seconds
        minute, second = divmod(total, 60)
        return MatchClock(period=clock.period, minute=minute, second=second)

    def _validate_event_ordering(self, event: MatchEvent) -> None:
        if event.event_id in self._processed_event_ids:
            raise DuplicateEvent(f"Duplicate event {event.event_id}")
        if event.sequence <= self._last_sequence:
            raise InvalidSequence(
                f"Event sequence {event.sequence} must be greater than {self._last_sequence}"
            )
        clock_seconds = event.match_clock.total_seconds()
        if self._last_clock_seconds and clock_seconds + 5 < self._last_clock_seconds:
            raise OutOfOrderEvent("major match clock regression detected")

    def _prepare_event(self, event: MatchEvent) -> MatchEvent:
        tags = list(event.tags)
        if isinstance(event, PassEvent):
            progressive = (event.end_location.x - event.location.x) >= self.config.progressive_pass_distance
            updates = {"progressive": progressive, "end_location": event.end_location.classified()}
            if event.pass_type.value == "THROUGH_BALL":
                tags.append(EventTag(code=TagCode.THROUGH_BALL_BEHIND_LINE, source=TagSource.RULE, confidence=0.9))
            event = event.model_copy(update=updates | {"tags": tags})
        if isinstance(event, CarryEvent):
            end = event.end_location.classified()
            if end.in_penalty_area:
                tags.append(EventTag(code=TagCode.BOX_ENTRY_DRIBBLE, source=TagSource.RULE, confidence=0.85))
            event = event.model_copy(update={"end_location": end, "tags": tags})
        if event.location.channel in {PitchChannel.HALF_SPACE_LEFT, PitchChannel.HALF_SPACE_RIGHT} and event.location.x > 0.62:
            tags.append(EventTag(code=TagCode.HALF_SPACE_PENETRATION, source=TagSource.RULE, confidence=0.8))
            event = event.model_copy(update={"tags": tags})
        return event

    def _update_possession(self, event: MatchEvent) -> PossessionChain | None:
        created = None
        possession_switch = self.active_possession is None or self.active_possession.team_id != event.team_id
        if possession_switch:
            if self.active_possession:
                self._close_possession(event.match_clock, PossessionEndReason.TURNOVER)
            self.active_possession = PossessionChain(
                match_id=event.match_id,
                team_id=event.team_id,
                start_time=event.match_clock,
                start_location=event.location,
                end_location=event.location,
                event_ids=[event.event_id],
                event_count=1,
            )
            self.possessions.append(self.active_possession)
            self.context = self.context.model_copy(update={"possession_team_id": event.team_id})
            created = self.active_possession
        else:
            assert self.active_possession is not None
            self.active_possession.event_ids.append(event.event_id)
            self.active_possession.event_count += 1
            self.active_possession.end_location = getattr(event, "end_location", event.location)
        possession = self.active_possession
        end_location = getattr(event, "end_location", event.location).classified()
        possession.end_location = end_location
        possession.duration_seconds = max(0.0, event.match_clock.total_seconds() - possession.start_time.total_seconds())
        possession.territory_gain = round((possession.end_location.x - possession.start_location.x) * 105, 1)
        possession.progression_distance += max(0.0, end_location.x - event.location.x) * 105
        possession.final_third_entries += int(end_location.third == PitchThird.FINAL)
        possession.box_entries += int(end_location.in_penalty_area)
        possession.shots += int(event.event_type == EventType.SHOT)
        possession.chances += int(isinstance(event, ShotEvent) and (event.shot_quality or 0) >= 0.35)
        if event.event_type in {EventType.GOAL, EventType.FOUL, EventType.OFFSIDE}:
            self._close_possession(event.match_clock, PossessionEndReason.GOAL if event.event_type == EventType.GOAL else PossessionEndReason.FOUL)
        return created

    def _close_possession(self, clock: MatchClock, reason: PossessionEndReason) -> None:
        if not self.active_possession:
            return
        self.active_possession.end_time = clock
        self.active_possession.duration_seconds = max(0.0, clock.total_seconds() - self.active_possession.start_time.total_seconds())
        self.active_possession.end_reason = reason

    def _update_attack(self, event: MatchEvent) -> AttackSequence | None:
        if not self.active_possession:
            return None
        recent_attack = self.attacks[-1] if self.attacks and self.attacks[-1].team_id == event.team_id and self.attacks[-1].outcome == "IN_PROGRESS" else None
        if not recent_attack:
            origin = AttackOrigin.TURNOVER if isinstance(event, DefensiveEvent) and event.event_type in {EventType.RECOVERY, EventType.INTERCEPTION} else AttackOrigin.OPEN_PLAY
            recent_attack = AttackSequence(
                match_id=event.match_id,
                team_id=event.team_id,
                start_time=event.match_clock,
                possession_ids=[self.active_possession.possession_id],
                origin=origin,
            )
            self.attacks.append(recent_attack)
        recent_attack.event_ids.append(event.event_id)
        if self.active_possession.possession_id not in recent_attack.possession_ids:
            recent_attack.possession_ids.append(self.active_possession.possession_id)
        end_location = getattr(event, "end_location", event.location)
        recent_attack.progression += max(0.0, end_location.x - event.location.x) * 105
        recent_attack.shot_created = recent_attack.shot_created or event.event_type == EventType.SHOT
        recent_attack.goal_created = recent_attack.goal_created or event.event_type == EventType.GOAL
        if any(tag.code == TagCode.HALF_SPACE_PENETRATION for tag in event.tags):
            recent_attack.spatial_pattern = "HALF_SPACE"
            if TagCode.HALF_SPACE_PENETRATION not in recent_attack.reason_codes:
                recent_attack.reason_codes.append(TagCode.HALF_SPACE_PENETRATION)
        if event.event_type in {EventType.SHOT, EventType.GOAL}:
            recent_attack.end_time = event.match_clock
            recent_attack.outcome = event.event_type.value
            recent_attack.chance_created = True
        return recent_attack

    def _update_transition(self, event: MatchEvent) -> TransitionSequence | None:
        if not self.active_possession:
            return None
        if event.event_type != EventType.SHOT:
            return None
        triggers = [
            previous
            for previous in reversed(self.events[-8:])
            if previous.team_id == event.team_id
            and isinstance(previous, DefensiveEvent)
            and previous.event_type in {EventType.RECOVERY, EventType.INTERCEPTION}
        ]
        if not triggers:
            return None
        trigger = triggers[0]
        progression_time = event.match_clock.total_seconds() - trigger.match_clock.total_seconds()
        territory_gain = (event.location.x - trigger.location.x) * 105
        if progression_time > self.config.transition_time_threshold or territory_gain < 25:
            return None
        return TransitionSequence(
            winning_team_id=event.team_id,
            trigger_event_id=trigger.event_id,
            recovery_location=trigger.location,
            progression_time_seconds=progression_time,
            territory_gain=round(territory_gain, 1),
            final_third_entry=True,
            box_entry=event.location.in_penalty_area,
            shot=True,
            chance=True,
            goal=False,
        )

    def _state_change(self, before: MatchState | None, after: MatchState, clock: MatchClock) -> StateChange | None:
        if not before:
            return None
        before_team = before.home if after.home.team_id == before.home.team_id else before.away
        after_team = after.home
        delta = after_team.pressure - before_team.pressure
        if abs(delta) >= self.config.state_change_threshold:
            return StateChange(dimension="home.pressure", before=before_team.pressure, after=after_team.pressure, delta=delta, timestamp=clock)
        return None

    def _rich_state_changes(
        self,
        before: MatchState | None,
        after: MatchState,
        event: MatchEvent,
    ) -> list[RichStateChange]:
        if not before:
            return []
        changes: list[RichStateChange] = []
        pairs = [(before.home, after.home), (before.away, after.away)]
        dimensions = [
            "control",
            "pressure",
            "threat",
            "territory",
            "tempo",
            "transition_intensity",
            "attacking_intensity",
            "defensive_stability",
            "action_impact",
        ]
        for previous_team, current_team in pairs:
            for dimension in dimensions:
                previous = float(getattr(previous_team, dimension))
                current = float(getattr(current_team, dimension))
                delta = current - previous
                if abs(delta) < self.config.state_change_threshold:
                    continue
                relative = 1.0 if previous == 0 and current else (
                    0.0 if previous == 0 else delta / abs(previous)
                )
                evidence = [
                    EvidenceRef(
                        source_type="state_change",
                        event_ids=[event.event_id],
                        metric=dimension,
                        value=round(current, 3),
                        baseline=round(previous, 3),
                        time_window="incremental",
                        explanation=f"{dimension} changed from {previous:.2f} to {current:.2f}",
                    )
                ]
                changes.append(
                    RichStateChange(
                        timestamp=event.match_clock,
                        team_id=current_team.team_id,
                        dimension=dimension,
                        before=round(previous, 3),
                        after=round(current, 3),
                        delta=round(delta, 3),
                        relative_change=round(relative, 3),
                        significance=min(1.0, abs(delta) + abs(relative) * 0.2),
                        evidence=evidence,
                    )
                )
        return changes

    def _detect_patterns(self, event: MatchEvent, state_change: StateChange | None) -> list[Pattern]:
        patterns: list[Pattern] = []
        patterns.extend(self._detect_pressure_patterns(event, state_change))
        patterns.extend(self._detect_counterattack(event))
        patterns.extend(self._detect_control_without_threat(event))
        patterns.extend(self._detect_player_influence(event))
        patterns.extend(self._detect_half_space(event))
        return [pattern for pattern in patterns if self._accept_pattern(pattern)]

    def _window(self, clock: MatchClock, seconds: int = 600) -> TimeWindow:
        start_seconds = max(0, clock.total_seconds() - seconds)
        start_minute, start_second = divmod(start_seconds, 60)
        return TimeWindow(start=MatchClock(period=clock.period, minute=start_minute, second=start_second), end=clock)

    def _detect_pressure_patterns(self, event: MatchEvent, state_change: StateChange | None) -> list[Pattern]:
        assert self.state is not None
        out: list[Pattern] = []
        metric = self.metrics.teams[event.team_id]
        if metric.pressure_events >= 5 and metric.final_third_recoveries >= 2:
            out.append(self._make_pattern(
                PatternType.HIGH_PRESS,
                event.team_id,
                event.match_clock,
                [
                    EvidenceRef(source_type="metric", event_ids=[e.event_id for e in self.events[-8:]], metric="pressure_events", value=metric.pressure_events, baseline=2, time_window="match-to-date", explanation=f"{metric.pressure_events} pressure events with {metric.final_third_recoveries} final-third recoveries"),
                ],
                [CausalFactor(factor_type=CausalFactorType.HIGH_PRESS, event_ids=[event.event_id], confidence=0.85)],
                [Consequence(consequence_type=ConsequenceType.TURNOVER, event_ids=[event.event_id], value=metric.forced_turnovers)],
                confidence=0.82,
                significance=0.76,
            ))
        if state_change and state_change.delta > 0:
            out.append(self._make_pattern(
                PatternType.PRESSURE_SHIFT,
                event.team_id,
                event.match_clock,
                [EvidenceRef(source_type="state_change", event_ids=[event.event_id], metric="pressure", value=round(state_change.after, 2), baseline=round(state_change.before, 2), time_window="current vs previous", explanation=f"Pressure rose from {state_change.before:.2f} to {state_change.after:.2f}")],
                [CausalFactor(factor_type=CausalFactorType.HIGH_PRESS, event_ids=[event.event_id], confidence=0.8)],
                [Consequence(consequence_type=ConsequenceType.TERRITORY_GAIN, event_ids=[event.event_id])],
                confidence=0.86,
                significance=min(1.0, 0.55 + abs(state_change.delta)),
            ))
        return out

    def _detect_counterattack(self, event: MatchEvent) -> list[Pattern]:
        if not self.transitions or event.event_type != EventType.SHOT:
            return []
        transition = self.transitions[-1]
        if transition.winning_team_id != event.team_id:
            return []
        return [self._make_pattern(
            PatternType.COUNTERATTACK,
            event.team_id,
            event.match_clock,
            [EvidenceRef(source_type="transition", event_ids=self.active_possession.event_ids if self.active_possession else [event.event_id], metric="territory_gain", value=transition.territory_gain, baseline=25, time_window=f"{transition.progression_time_seconds:.1f}s", explanation=f"Rapid attack gained {transition.territory_gain:.1f}m and ended in a shot")],
            [CausalFactor(factor_type=CausalFactorType.RAPID_TRANSITION, event_ids=[transition.trigger_event_id], confidence=0.88)],
            [Consequence(consequence_type=ConsequenceType.SHOT, event_ids=[event.event_id])],
            confidence=0.87,
            significance=0.84,
        )]

    def _detect_control_without_threat(self, event: MatchEvent) -> list[Pattern]:
        metric = self.metrics.teams[event.team_id]
        if metric.possession_pct >= 0.62 and metric.final_third_entries >= 3 and metric.threat_index < 0.25 and metric.box_entries <= 1:
            return [self._make_pattern(
                PatternType.CONTROL_WITHOUT_THREAT,
                event.team_id,
                event.match_clock,
                [EvidenceRef(source_type="metric", event_ids=[e.event_id for e in self.events if e.team_id == event.team_id][-10:], metric="control_without_threat", value=metric.possession_pct, baseline=0.62, time_window="match-to-date", explanation="High possession and territory have not produced box entries or threat")],
                [],
                [Consequence(consequence_type=ConsequenceType.TERRITORY_GAIN)],
                confidence=0.78,
                significance=0.62,
            )]
        return []

    def _detect_player_influence(self, event: MatchEvent) -> list[Pattern]:
        if not event.player_id:
            return []
        player = self.metrics.players.get(event.player_id)
        if not player or player.influence_score < 0.35:
            return []
        return [self._make_pattern(
            PatternType.PLAYER_INFLUENCE,
            event.team_id,
            event.match_clock,
            [EvidenceRef(source_type="player_metric", event_ids=[event.event_id], metric="influence_score", value=round(player.influence_score, 2), baseline=0.35, time_window="match-to-date", explanation="Player contribution exceeds baseline across progression, shots and defensive actions")],
            [],
            [Consequence(consequence_type=ConsequenceType.TERRITORY_GAIN, event_ids=[event.event_id])],
            confidence=0.74,
            significance=player.influence_score,
            player_id=event.player_id,
        )]

    def _detect_half_space(self, event: MatchEvent) -> list[Pattern]:
        recent = [
            e for e in self.events[-12:] + [event]
            if e.team_id == event.team_id and any(tag.code == TagCode.HALF_SPACE_PENETRATION for tag in e.tags)
        ]
        if len(recent) < 3:
            return []
        return [self._make_pattern(
            PatternType.HALF_SPACE_EXPLOITATION,
            event.team_id,
            event.match_clock,
            [EvidenceRef(source_type="tags", event_ids=[e.event_id for e in recent], metric="half_space_penetrations", value=len(recent), baseline=3, time_window="recent events", explanation=f"{len(recent)} half-space penetrations with final-third access")],
            [CausalFactor(factor_type=CausalFactorType.SPACE_CREATED, event_ids=[e.event_id for e in recent], confidence=0.75)],
            [Consequence(consequence_type=ConsequenceType.BOX_ENTRY, event_ids=[event.event_id])],
            confidence=0.8,
            significance=0.72,
        )]

    def _make_pattern(
        self,
        pattern_type: PatternType,
        team_id: UUID,
        clock: MatchClock,
        evidence: list[EvidenceRef],
        causes: list[CausalFactor],
        consequences: list[Consequence],
        confidence: float,
        significance: float,
        player_id: UUID | None = None,
    ) -> Pattern:
        evidence = evidence + self._action_impact_evidence(evidence, clock)
        return Pattern(
            match_id=self.context.match_id,
            pattern_type=pattern_type,
            team_id=team_id,
            player_id=player_id,
            detected_at=clock,
            observation_window=self._window(clock),
            confidence=confidence,
            significance=significance,
            evidence=evidence,
            causes=causes,
            consequences=consequences,
            state_before={},
            state_after={},
            deduplication_key=f"{pattern_type.value}:{team_id}:{clock.total_seconds() // self.config.deduplication_window}",
        )

    def _accept_pattern(self, pattern: Pattern) -> bool:
        if pattern.significance < self.config.pattern_significance_threshold:
            return False
        current_second = pattern.detected_at.total_seconds()
        previous_second = self._dedupe_seconds.get(pattern.deduplication_key)
        if previous_second is not None and current_second - previous_second < self.config.deduplication_window:
            return False
        self._dedupe_seconds[pattern.deduplication_key] = current_second
        return True

    def _candidate_from_pattern(self, pattern: Pattern) -> InsightCandidate:
        action_impact = max(
            0.0,
            min(
                1.0,
                sum(
                    float(evidence.value)
                    for evidence in pattern.evidence
                    if evidence.source_type == "action_impact" and isinstance(evidence.value, (int, float))
                ),
            ),
        )
        consequence_magnitude = max(
            [min(1.0, float(consequence.value)) for consequence in pattern.consequences if consequence.value is not None]
            or [pattern.significance]
        )
        return InsightCandidate(
            pattern_id=pattern.pattern_id,
            significance=pattern.significance,
            confidence=pattern.confidence,
            novelty=0.86,
            recency=0.95,
            audience_relevance=0.9,
            action_impact=action_impact,
            consequence_magnitude=consequence_magnitude,
            deduplication_key=pattern.deduplication_key,
            evidence=pattern.evidence,
        )

    def _causal_chain_from_pattern(self, pattern: Pattern) -> CausalChain:
        steps: list[CausalStep] = []
        for cause in pattern.causes:
            steps.append(
                CausalStep(
                    label=cause.factor_type.value,
                    factor_type=cause.factor_type,
                    event_ids=cause.event_ids,
                    metrics=[e.metric for e in pattern.evidence],
                )
            )
        if pattern.pattern_type == PatternType.COUNTERATTACK:
            steps.extend(
                [
                    CausalStep(
                        label="TURNOVER",
                        factor_type=CausalFactorType.TURNOVER,
                        event_ids=pattern.evidence[0].event_ids[:1] if pattern.evidence else [],
                    ),
                    CausalStep(
                        label="RAPID_TRANSITION",
                        factor_type=CausalFactorType.RAPID_TRANSITION,
                        event_ids=pattern.evidence[0].event_ids if pattern.evidence else [],
                        metrics=["territory_gain"],
                    ),
                ]
            )
        if pattern.pattern_type == PatternType.HALF_SPACE_EXPLOITATION:
            steps.append(
                CausalStep(
                    label="HALF_SPACE_ACCESS",
                    factor_type=CausalFactorType.HALF_SPACE_ACCESS,
                    event_ids=pattern.evidence[0].event_ids if pattern.evidence else [],
                    metrics=["half_space_penetrations"],
                )
            )
        for consequence in pattern.consequences:
            steps.append(
                CausalStep(
                    label=consequence.consequence_type.value,
                    consequence_type=consequence.consequence_type,
                    event_ids=consequence.event_ids,
                )
            )
        if not steps:
            steps.append(
                CausalStep(
                    label=pattern.pattern_type.value,
                    event_ids=[event_id for evidence in pattern.evidence for event_id in evidence.event_ids],
                    metrics=[evidence.metric for evidence in pattern.evidence],
                )
            )
        return CausalChain(
            pattern_id=pattern.pattern_id,
            match_id=pattern.match_id,
            team_id=pattern.team_id,
            pattern_type=pattern.pattern_type,
            created_at=pattern.detected_at,
            steps=steps,
            impacts=[
                Impact(
                    description=f"{pattern.pattern_type.value} significance",
                    magnitude=pattern.significance,
                    metric="significance",
                    value=pattern.significance,
                )
            ],
        )

    def _claim_from_pattern(self, pattern: Pattern) -> InsightClaim:
        evidence = pattern.evidence[0]
        claim_type = {
            PatternType.PRESSURE_SHIFT: ClaimType.TEAM_PRESSURE_INCREASE,
            PatternType.HIGH_PRESS: ClaimType.TEAM_PRESSURE_INCREASE,
            PatternType.COUNTERATTACK: ClaimType.COUNTERATTACK_DETECTED,
            PatternType.HALF_SPACE_EXPLOITATION: ClaimType.HALF_SPACE_EXPLOITATION,
            PatternType.CONTROL_WITHOUT_THREAT: ClaimType.CONTROL_WITHOUT_THREAT,
            PatternType.PLAYER_INFLUENCE: ClaimType.PLAYER_INFLUENCE,
            PatternType.ATTACKING_SURGE: ClaimType.ATTACKING_SURGE,
            PatternType.DEFENSIVE_BREAKDOWN: ClaimType.DEFENSIVE_BREAKDOWN,
            PatternType.MOMENTUM_SHIFT: ClaimType.MOMENTUM_SHIFT,
        }.get(pattern.pattern_type, ClaimType.MOMENTUM_SHIFT)
        predicate = claim_type.value.lower()
        return InsightClaim(
            claim_type=claim_type,
            subject_team_id=pattern.team_id,
            subject_player_id=pattern.player_id,
            predicate=predicate,
            object={
                "metric": evidence.metric,
                "current": evidence.value,
                "previous": evidence.baseline,
                "window": evidence.time_window,
            },
            pattern_id=pattern.pattern_id,
            pattern_type=pattern.pattern_type,
            evidence=pattern.evidence,
            observation_window=pattern.observation_window,
            claim_confidence=pattern.confidence,
        )

    def _trace_for_event(
        self,
        event: MatchEvent,
        action_impact: ActionImpact,
        patterns: list[Pattern],
        candidates: list[InsightCandidate],
        claims: list[InsightClaim],
        validations: list[ValidationResult],
        insights: list[Insight],
    ) -> ProcessingTrace:
        return ProcessingTrace(
            event_id=event.event_id,
            insight_id=insights[-1].insight_id if insights else None,
            steps=[
                ProcessingTraceStep(
                    step="event_processing",
                    status="PASS",
                    detail=f"Processed event {event.sequence}",
                    event_ids=[event.event_id],
                ),
                ProcessingTraceStep(
                    step="action_impact",
                    status="PASS",
                    detail=f"Net impact {action_impact.net_impact:+.2f}",
                    event_ids=[event.event_id],
                ),
                ProcessingTraceStep(
                    step="pattern_detection",
                    status="PASS",
                    detail=f"{len(patterns)} patterns detected",
                    event_ids=[event.event_id],
                ),
                ProcessingTraceStep(
                    step="candidate_generation",
                    status="PASS",
                    detail=f"{len(candidates)} candidates created",
                ),
                ProcessingTraceStep(
                    step="claim_creation",
                    status="PASS",
                    detail=f"{len(claims)} claims created",
                ),
                ProcessingTraceStep(
                    step="validation",
                    status="PASS" if all(v.valid for v in validations) else "FAIL",
                    detail=f"{sum(v.valid for v in validations)} validations passed",
                ),
                ProcessingTraceStep(
                    step="insight_creation",
                    status="PASS",
                    detail=f"{len(insights)} insights available",
                ),
            ],
        )

    def _update_telemetry(
        self,
        duration_ms: float,
        patterns: list[Pattern],
        candidates: list[InsightCandidate],
        validations: list[ValidationResult],
        insights: list[Insight],
    ) -> None:
        self.telemetry.events_processed += 1
        self.telemetry.processing_duration_ms = round(
            self.telemetry.processing_duration_ms + duration_ms,
            3,
        )
        self.telemetry.patterns_evaluated += len(PatternType)
        self.telemetry.patterns_detected += len(patterns)
        self.telemetry.candidates_created += len(candidates)
        self.telemetry.insights_validated += sum(validation.valid for validation in validations)
        self.telemetry.insights_rejected += sum(not validation.valid for validation in validations)
        suppressed = len(candidates) - len(insights)
        if suppressed > 0:
            self.telemetry.candidates_suppressed += suppressed

    def _metric_changes(self, event: MatchEvent) -> list[MetricValue]:
        changes = [MetricValue(name="events_processed", team_id=event.team_id, value=float(len(self.events)))]
        impact = next((item for item in reversed(self.action_impacts) if item.event_id == event.event_id), None)
        if impact:
            changes.append(MetricValue(name="net_action_impact", team_id=event.team_id, player_id=event.player_id, value=impact.net_impact))
        if isinstance(event, ShotEvent):
            changes.append(MetricValue(name="shots", team_id=event.team_id, value=float(self.metrics.teams[event.team_id].shots)))
        if isinstance(event, DefensiveEvent) and event.event_type == EventType.PRESSURE:
            changes.append(MetricValue(name="pressure_events", team_id=event.team_id, value=float(self.metrics.teams[event.team_id].pressure_events)))
        return changes

    def _action_impact_evidence(
        self,
        evidence: list[EvidenceRef],
        clock: MatchClock,
    ) -> list[EvidenceRef]:
        event_ids = {event_id for item in evidence for event_id in item.event_ids}
        impacts = [impact for impact in self.action_impacts if impact.event_id in event_ids]
        if not impacts:
            return []
        value = round(sum(impact.net_impact for impact in impacts), 3)
        return [
            EvidenceRef(
                source_type="action_impact",
                event_ids=[impact.event_id for impact in impacts],
                impact_ids=[impact.action_id for impact in impacts],
                metric="net_action_impact",
                value=value,
                baseline=0.0,
                time_window=f"through {clock.display()}",
                explanation=f"Related actions produced {value:+.2f} deterministic net action impact",
            )
        ]
