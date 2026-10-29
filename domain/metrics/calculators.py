from __future__ import annotations

from collections import defaultdict
from math import cos, radians
from uuid import UUID

from pydantic import Field

from domain.common import DomainModel
from domain.enums import EventOutcome, EventType, PitchThird, PressureLevel, ShotOutcome
from domain.events.base import MatchEvent
from domain.events.defensive import DefensiveEvent
from domain.events.offensive import CarryEvent, PassEvent, ShotEvent
from domain.match.match import MatchContext
from domain.match.state import MatchState, TeamState
from domain.metrics.impact import ActionImpact, aggregate_impacts
from domain.sequences.possession import PossessionChain
from domain.sequences.transition import TransitionSequence


class TeamMetrics(DomainModel):
    team_id: UUID
    possession_pct: float = 0.0
    possession_count: int = 0
    average_possession_duration: float = 0.0
    passes_per_possession: float = 0.0
    progressive_passes: int = 0
    progressive_distance: float = 0.0
    final_third_entries: int = 0
    box_entries: int = 0
    forward_pass_ratio: float = 0.0
    shots: int = 0
    shots_on_target: int = 0
    shot_quality: float = 0.0
    chance_count: int = 0
    big_chance_count: int = 0
    threat_index: float = 0.0
    pressure_events: int = 0
    high_pressure_recoveries: int = 0
    final_third_recoveries: int = 0
    forced_turnovers: int = 0
    pressure_to_shot: int = 0
    pressure_to_chance: int = 0
    pressure_to_goal: int = 0
    transition_count: int = 0
    transition_to_shot: int = 0
    transition_to_chance: int = 0
    transition_to_goal: int = 0
    attacking_action_impact: float = 0.0
    defensive_action_impact: float = 0.0
    net_action_impact: float = 0.0
    transition_action_impact: float = 0.0


class PlayerMetrics(DomainModel):
    player_id: UUID
    team_id: UUID
    passes: int = 0
    progressive_passes: int = 0
    carries: int = 0
    chances_created: int = 0
    shots: int = 0
    pressure_actions: int = 0
    recoveries: int = 0
    territory_progressed: float = 0.0
    influence_score: float = 0.0
    attacking_action_impact: float = 0.0
    defensive_action_impact: float = 0.0
    net_action_impact: float = 0.0
    transition_action_impact: float = 0.0


class MetricSnapshot(DomainModel):
    teams: dict[UUID, TeamMetrics] = Field(default_factory=dict)
    players: dict[UUID, PlayerMetrics] = Field(default_factory=dict)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def shot_quality(event: ShotEvent) -> tuple[float, list[str]]:
    score = 0.1
    factors: list[str] = []
    if event.distance <= 12:
        score += 0.28
        factors.append("+ close distance")
    elif event.distance <= 22:
        score += 0.16
        factors.append("+ medium distance")
    else:
        score -= 0.04
        factors.append("- long distance")
    centrality = max(0.0, cos(radians(abs(90 - event.angle))))
    score += centrality * 0.22
    if centrality > 0.65:
        factors.append("+ central angle")
    if event.location.in_penalty_area:
        score += 0.18
        factors.append("+ inside box")
    if event.shot_outcome in {ShotOutcome.ON_TARGET, ShotOutcome.SAVED, ShotOutcome.GOAL}:
        score += 0.12
        factors.append("+ on target")
    if event.pressure_level == PressureLevel.HIGH:
        score -= 0.14
        factors.append("- high defensive pressure")
    elif event.pressure_level == PressureLevel.MEDIUM:
        score -= 0.07
        factors.append("- moderate pressure")
    return round(_clamp(score), 3), factors


def calculate_metrics(
    context: MatchContext,
    events: list[MatchEvent],
    possessions: list[PossessionChain],
    transitions: list[TransitionSequence],
    action_impacts: list[ActionImpact] | None = None,
) -> MetricSnapshot:
    teams = {
        context.home_team.team_id: TeamMetrics(team_id=context.home_team.team_id),
        context.away_team.team_id: TeamMetrics(team_id=context.away_team.team_id),
    }
    players: dict[UUID, PlayerMetrics] = {}
    total_possession_seconds = sum(p.duration_seconds for p in possessions) or 1.0
    team_possession_seconds: dict[UUID, float] = defaultdict(float)
    team_passes: dict[UUID, int] = defaultdict(int)
    forward_passes: dict[UUID, int] = defaultdict(int)
    shot_quality_sum: dict[UUID, float] = defaultdict(float)
    for possession in possessions:
        metric = teams[possession.team_id]
        metric.possession_count += 1
        metric.final_third_entries += possession.final_third_entries
        metric.box_entries += possession.box_entries
        metric.shots += possession.shots
        metric.chance_count += possession.chances
        metric.progressive_distance += possession.progression_distance
        team_possession_seconds[possession.team_id] += possession.duration_seconds
    for event in events:
        if event.player_id and event.player_id not in players:
            players[event.player_id] = PlayerMetrics(player_id=event.player_id, team_id=event.team_id)
        player = players.get(event.player_id) if event.player_id else None
        if isinstance(event, PassEvent):
            team_passes[event.team_id] += 1
            if event.end_location.x > event.location.x:
                forward_passes[event.team_id] += 1
            if player:
                player.passes += 1
                player.territory_progressed += max(0.0, event.end_location.x - event.location.x) * 105
            if event.progressive:
                teams[event.team_id].progressive_passes += 1
                if player:
                    player.progressive_passes += 1
        elif isinstance(event, CarryEvent):
            if player:
                player.carries += 1
                player.territory_progressed += max(0.0, event.end_location.x - event.start_location.x) * 105
        elif isinstance(event, ShotEvent):
            quality, factors = shot_quality(event)
            event.shot_quality = quality
            event.shot_quality_factors = factors
            teams[event.team_id].shots += 1
            shot_quality_sum[event.team_id] += quality
            if event.shot_outcome in {ShotOutcome.ON_TARGET, ShotOutcome.SAVED, ShotOutcome.GOAL}:
                teams[event.team_id].shots_on_target += 1
            if quality >= 0.35:
                teams[event.team_id].chance_count += 1
            if quality >= 0.6:
                teams[event.team_id].big_chance_count += 1
            if player:
                player.shots += 1
        elif isinstance(event, DefensiveEvent):
            if event.event_type == EventType.PRESSURE:
                teams[event.team_id].pressure_events += 1
                if player:
                    player.pressure_actions += 1
            if event.event_type == EventType.RECOVERY:
                if event.location.third == PitchThird.FINAL:
                    teams[event.team_id].final_third_recoveries += 1
                if player:
                    player.recoveries += 1
            if event.forced_turnover or event.outcome == EventOutcome.WON:
                teams[event.team_id].forced_turnovers += 1
                if event.location.third == PitchThird.FINAL:
                    teams[event.team_id].high_pressure_recoveries += 1
    for transition in transitions:
        metric = teams[transition.winning_team_id]
        metric.transition_count += 1
        metric.transition_to_shot += int(transition.shot)
        metric.transition_to_chance += int(transition.chance)
        metric.transition_to_goal += int(transition.goal)
    impacts = aggregate_impacts(context, action_impacts or [])
    for team_id, team_impact in impacts.teams.items():
        metric = teams.setdefault(team_id, TeamMetrics(team_id=team_id))
        metric.attacking_action_impact = team_impact.team_attacking_impact
        metric.defensive_action_impact = team_impact.team_defensive_impact
        metric.net_action_impact = team_impact.team_total_impact
        metric.transition_action_impact = team_impact.team_transition_impact
    for player_id, player_impact in impacts.players.items():
        player = players.setdefault(player_id, PlayerMetrics(player_id=player_id, team_id=player_impact.team_id))
        player.attacking_action_impact = player_impact.player_attacking_impact
        player.defensive_action_impact = player_impact.player_defensive_impact
        player.net_action_impact = player_impact.player_total_impact
        player.transition_action_impact = player_impact.player_transition_impact
    for team_id, metric in teams.items():
        metric.possession_pct = round(team_possession_seconds[team_id] / total_possession_seconds, 3)
        metric.average_possession_duration = round(
            team_possession_seconds[team_id] / metric.possession_count, 2
        ) if metric.possession_count else 0.0
        metric.passes_per_possession = round(team_passes[team_id] / metric.possession_count, 2) if metric.possession_count else 0.0
        metric.forward_pass_ratio = round(forward_passes[team_id] / team_passes[team_id], 3) if team_passes[team_id] else 0.0
        metric.shot_quality = round(shot_quality_sum[team_id] / metric.shots, 3) if metric.shots else 0.0
        metric.threat_index = _clamp((metric.shots * 0.08) + (metric.chance_count * 0.12) + (metric.box_entries * 0.04) + metric.shot_quality)
    for player in players.values():
        player.influence_score = _clamp(
            (player.progressive_passes * 0.08)
            + (player.carries * 0.04)
            + (player.shots * 0.12)
            + (player.pressure_actions * 0.03)
            + (player.recoveries * 0.05)
            + (player.territory_progressed / 400)
            + max(0.0, player.net_action_impact) * 0.2
        )
    return MetricSnapshot(teams=teams, players=players)


def calculate_match_state(context: MatchContext, metrics: MetricSnapshot) -> MatchState:
    home_metrics = metrics.teams[context.home_team.team_id]
    away_metrics = metrics.teams[context.away_team.team_id]

    def make_state(metric: TeamMetrics) -> TeamState:
        territory = _clamp((metric.final_third_entries * 0.08) + (metric.box_entries * 0.12) + (metric.progressive_distance / 250))
        pressure = _clamp((metric.pressure_events * 0.05) + (metric.final_third_recoveries * 0.12) + (metric.forced_turnovers * 0.08))
        tempo = _clamp((metric.possession_count * 0.04) + (metric.progressive_passes * 0.05) + (metric.transition_count * 0.1))
        attack = _clamp((metric.shots * 0.08) + territory + metric.threat_index)
        impact_score = max(-1.0, min(1.0, metric.net_action_impact / 2.0))
        return TeamState(
            team_id=metric.team_id,
            control=_clamp((metric.possession_pct * 0.7) + (territory * 0.3)),
            pressure=pressure,
            threat=metric.threat_index,
            territory=territory,
            tempo=tempo,
            transition_intensity=_clamp(metric.transition_count * 0.18),
            attacking_intensity=_clamp(attack + max(0.0, metric.attacking_action_impact) * 0.08),
            defensive_stability=_clamp(1.0 - (metric.shots * 0.04) + max(0.0, metric.defensive_action_impact) * 0.06),
            action_impact=impact_score,
        )

    home = make_state(home_metrics)
    away = make_state(away_metrics)
    home_score = home.control + home.pressure + home.threat + home.territory
    away_score = away.control + away.pressure + away.threat + away.territory
    dominant = context.home_team.team_id if home_score >= away_score else context.away_team.team_id
    labels = []
    if home.pressure > 0.72 or away.pressure > 0.72:
        labels.append("HIGH_PRESSURE")
    if abs(home.threat - away.threat) > 0.25:
        labels.append("THREAT_IMBALANCE")
    chaos = _clamp((home.tempo + away.tempo + home.transition_intensity + away.transition_intensity) / 4)
    return MatchState(
        timestamp=context.current_clock,
        home=home,
        away=away,
        dominant_team_id=dominant,
        state_labels=labels,
        momentum_direction=dominant,
        momentum_strength=_clamp(abs(home_score - away_score) / 4),
        chaos=chaos,
    )
