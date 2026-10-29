from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import Field

from domain.common import DomainModel, Location, MatchClock
from domain.enums import EventOutcome, EventType, PitchThird, PressureLevel, ShotOutcome
from domain.events.base import MatchEvent
from domain.events.defensive import DefensiveEvent
from domain.events.offensive import CarryEvent, PassEvent, ShotEvent
from domain.insights.evidence import EvidenceRef
from domain.match.match import MatchContext
from domain.match.state import MatchState

CALCULATION_VERSION = "action-impact.v1"


class ActionImpactFactor(DomainModel):
    name: str
    value: float
    explanation: str


class ActionStateSnapshot(DomainModel):
    match_clock: MatchClock
    possession_team_id: UUID | None = None
    location_x: float
    location_y: float
    location_third: str | None = None
    attacking_opportunity: float = Field(ge=0.0, le=1.0)
    opponent_opportunity: float = Field(ge=0.0, le=1.0)
    pressure_level: PressureLevel | None = None


class ActionImpact(DomainModel):
    action_id: UUID = Field(default_factory=uuid4)
    event_id: UUID
    match_id: UUID
    sequence: int
    team_id: UUID
    player_id: UUID | None = None
    event_type: EventType
    attacking_value_delta: float
    defensive_value_delta: float
    net_impact: float
    state_before: ActionStateSnapshot
    state_after: ActionStateSnapshot
    contributing_factors: list[ActionImpactFactor] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    calculation_version: str = CALCULATION_VERSION
    evidence: list[EvidenceRef] = Field(default_factory=list)


class PlayerImpact(DomainModel):
    player_id: UUID
    team_id: UUID
    player_total_impact: float = 0.0
    player_attacking_impact: float = 0.0
    player_defensive_impact: float = 0.0
    player_transition_impact: float = 0.0
    actions: int = 0


class TeamImpact(DomainModel):
    team_id: UUID
    team_total_impact: float = 0.0
    team_attacking_impact: float = 0.0
    team_defensive_impact: float = 0.0
    team_transition_impact: float = 0.0
    actions: int = 0


class ImpactSnapshot(DomainModel):
    teams: dict[UUID, TeamImpact] = Field(default_factory=dict)
    players: dict[UUID, PlayerImpact] = Field(default_factory=dict)


def calculate_action_impact(
    context: MatchContext,
    event: MatchEvent,
    previous_state: MatchState | None = None,
) -> ActionImpact:
    action_id = uuid5(NAMESPACE_URL, f"squeeze.action-impact:{event.event_id}")
    end_location = _end_location(event)
    before_attack = _attacking_opportunity(event.location, event)
    after_attack = _attacking_opportunity(end_location, event)
    before_opponent = _opponent_opportunity(event.location, event)
    after_opponent = _opponent_opportunity(end_location, event)
    factors: list[ActionImpactFactor] = []

    attack_delta = 0.0
    defense_delta = 0.0

    progression = max(0.0, end_location.x - event.location.x)
    if progression:
        value = round(progression * (0.28 + end_location.x * 0.32), 3)
        attack_delta += value
        factors.append(ActionImpactFactor(name="territory_progression", value=value, explanation="Moved the action closer to goal."))

    if event.location.third != PitchThird.FINAL and end_location.third == PitchThird.FINAL:
        attack_delta += 0.08
        factors.append(ActionImpactFactor(name="final_third_entry", value=0.08, explanation="Entered the final third."))

    if not event.location.in_penalty_area and end_location.in_penalty_area:
        attack_delta += 0.12
        factors.append(ActionImpactFactor(name="box_entry", value=0.12, explanation="Entered the penalty area."))

    if isinstance(event, ShotEvent):
        shot_value = event.shot_quality if event.shot_quality is not None else _shot_proxy(event)
        attack_delta += shot_value
        factors.append(ActionImpactFactor(name="shot_quality_proxy", value=round(shot_value, 3), explanation="Shot quality proxy from location, angle and outcome."))
        if event.shot_outcome == ShotOutcome.GOAL:
            attack_delta += 0.3
            factors.append(ActionImpactFactor(name="goal_outcome", value=0.3, explanation="The shot became a goal."))

    if isinstance(event, DefensiveEvent):
        if event.event_type in {EventType.RECOVERY, EventType.INTERCEPTION, EventType.TACKLE} and (
            event.outcome == EventOutcome.WON or event.forced_turnover
        ):
            turnover_value = 0.08 + (event.location.x * 0.16)
            attack_delta += turnover_value
            defense_delta += 0.08 + (event.location.x * 0.1)
            factors.append(ActionImpactFactor(name="turnover_creation", value=round(turnover_value, 3), explanation="Won the ball and created possession value."))
        elif event.event_type == EventType.PRESSURE:
            pressure_value = _pressure_bonus(_pressure_level(event))
            defense_delta += pressure_value
            factors.append(ActionImpactFactor(name="pressure_disruption", value=round(pressure_value, 3), explanation="Applied pressure that disrupted opponent possession."))

    if _action_failed(event):
        risk = 0.08 + (event.location.x * 0.15) + _pressure_bonus(_pressure_level(event)) * 0.5
        attack_delta -= risk
        defense_delta -= risk * 0.4
        after_opponent = min(1.0, after_opponent + risk)
        factors.append(ActionImpactFactor(name="execution_risk", value=round(-risk, 3), explanation="Failed action increased transition risk."))
    elif isinstance(event, (PassEvent, CarryEvent)) and event.outcome in {EventOutcome.SUCCESS, EventOutcome.COMPLETE}:
        retention = 0.03 + max(0.0, after_attack - before_attack) * 0.25
        attack_delta += retention
        factors.append(ActionImpactFactor(name="possession_retention", value=round(retention, 3), explanation="Retained possession in a more useful state."))

    state_boost = _state_pressure_boost(previous_state, event.team_id)
    if state_boost:
        defense_delta += state_boost
        factors.append(ActionImpactFactor(name="team_pressure_state", value=round(state_boost, 3), explanation="Action occurred during a strong team pressure state."))

    attacking_value_delta = round(_clamp_signed(attack_delta), 3)
    defensive_value_delta = round(_clamp_signed(defense_delta), 3)
    net_impact = round(_clamp_signed(attacking_value_delta + defensive_value_delta - max(0.0, after_opponent - before_opponent) * 0.25), 3)
    confidence = 0.78 if factors else 0.55
    if isinstance(event, ShotEvent):
        confidence = 0.86
    elif isinstance(event, DefensiveEvent):
        confidence = 0.82

    state_before = ActionStateSnapshot(
        match_clock=event.match_clock,
        possession_team_id=context.possession_team_id,
        location_x=event.location.x,
        location_y=event.location.y,
        location_third=event.location.third.value if event.location.third else None,
        attacking_opportunity=round(before_attack, 3),
        opponent_opportunity=round(before_opponent, 3),
        pressure_level=_pressure_level(event),
    )
    state_after = ActionStateSnapshot(
        match_clock=event.match_clock,
        possession_team_id=event.team_id,
        location_x=end_location.x,
        location_y=end_location.y,
        location_third=end_location.third.value if end_location.third else None,
        attacking_opportunity=round(after_attack, 3),
        opponent_opportunity=round(after_opponent, 3),
        pressure_level=_pressure_level(event),
    )
    evidence = [
        EvidenceRef(
            evidence_id=uuid5(NAMESPACE_URL, f"squeeze.action-impact-evidence:{action_id}"),
            source_type="action_impact",
            event_ids=[event.event_id],
            impact_ids=[action_id],
            metric="net_impact",
            value=net_impact,
            baseline=0.0,
            time_window="single_action",
            explanation=f"{event.event_type.value} changed net action impact by {net_impact:+.2f}",
        )
    ]
    return ActionImpact(
        action_id=action_id,
        event_id=event.event_id,
        match_id=event.match_id,
        sequence=event.sequence,
        team_id=event.team_id,
        player_id=event.player_id,
        event_type=event.event_type,
        attacking_value_delta=attacking_value_delta,
        defensive_value_delta=defensive_value_delta,
        net_impact=net_impact,
        state_before=state_before,
        state_after=state_after,
        contributing_factors=factors,
        confidence=confidence,
        evidence=evidence,
    )


def aggregate_impacts(
    context: MatchContext,
    impacts: list[ActionImpact],
) -> ImpactSnapshot:
    teams = {
        context.home_team.team_id: TeamImpact(team_id=context.home_team.team_id),
        context.away_team.team_id: TeamImpact(team_id=context.away_team.team_id),
    }
    players: dict[UUID, PlayerImpact] = {}
    for impact in impacts:
        team = teams.setdefault(impact.team_id, TeamImpact(team_id=impact.team_id))
        team.team_total_impact = round(team.team_total_impact + impact.net_impact, 3)
        team.team_attacking_impact = round(team.team_attacking_impact + impact.attacking_value_delta, 3)
        team.team_defensive_impact = round(team.team_defensive_impact + impact.defensive_value_delta, 3)
        team.actions += 1
        if _is_transition_impact(impact):
            team.team_transition_impact = round(team.team_transition_impact + impact.net_impact, 3)
        if impact.player_id is None:
            continue
        player = players.setdefault(
            impact.player_id,
            PlayerImpact(player_id=impact.player_id, team_id=impact.team_id),
        )
        player.player_total_impact = round(player.player_total_impact + impact.net_impact, 3)
        player.player_attacking_impact = round(player.player_attacking_impact + impact.attacking_value_delta, 3)
        player.player_defensive_impact = round(player.player_defensive_impact + impact.defensive_value_delta, 3)
        player.actions += 1
        if _is_transition_impact(impact):
            player.player_transition_impact = round(player.player_transition_impact + impact.net_impact, 3)
    return ImpactSnapshot(teams=teams, players=players)


def _end_location(event: MatchEvent) -> Location:
    return getattr(event, "end_location", event.location).classified()


def _attacking_opportunity(location: Location, event: MatchEvent) -> float:
    classified = location.classified()
    value = classified.x * 0.45
    if classified.third == PitchThird.FINAL:
        value += 0.12
    if classified.in_penalty_area:
        value += 0.18
    if 0.38 <= classified.y <= 0.62:
        value += 0.04
    if _pressure_level(event) == PressureLevel.HIGH:
        value -= 0.05
    elif _pressure_level(event) == PressureLevel.MEDIUM:
        value -= 0.025
    return _clamp(value)


def _opponent_opportunity(location: Location, event: MatchEvent) -> float:
    if _action_failed(event):
        return _clamp(0.18 + location.x * 0.35)
    return _clamp(0.08 + max(0.0, 0.5 - location.x) * 0.2)


def _shot_proxy(event: ShotEvent) -> float:
    value = 0.1
    if event.distance <= 12:
        value += 0.28
    elif event.distance <= 22:
        value += 0.16
    else:
        value -= 0.04
    if event.location.in_penalty_area:
        value += 0.18
    if event.shot_outcome in {ShotOutcome.ON_TARGET, ShotOutcome.SAVED, ShotOutcome.GOAL}:
        value += 0.12
    if event.pressure_level == PressureLevel.HIGH:
        value -= 0.14
    elif event.pressure_level == PressureLevel.MEDIUM:
        value -= 0.07
    return _clamp(value)


def _action_failed(event: MatchEvent) -> bool:
    return event.outcome in {EventOutcome.FAILURE, EventOutcome.INCOMPLETE, EventOutcome.LOST}


def _pressure_level(event: MatchEvent) -> PressureLevel:
    direct = getattr(event, "pressure_level", None)
    if isinstance(direct, PressureLevel):
        return direct
    return event.context.pressure_level


def _pressure_bonus(level: PressureLevel) -> float:
    return {
        PressureLevel.NONE: 0.0,
        PressureLevel.LOW: 0.015,
        PressureLevel.MEDIUM: 0.035,
        PressureLevel.HIGH: 0.065,
    }[level]


def _state_pressure_boost(state: MatchState | None, team_id: UUID) -> float:
    if state is None:
        return 0.0
    team_state = state.home if state.home.team_id == team_id else state.away
    return 0.025 if team_state.pressure >= 0.7 else 0.0


def _is_transition_impact(impact: ActionImpact) -> bool:
    return any(factor.name in {"turnover_creation", "territory_progression", "box_entry"} for factor in impact.contributing_factors)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _clamp_signed(value: float) -> float:
    return max(-1.0, min(1.0, value))
