from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from domain.common import DomainModel, EventContext, Location, MatchClock
from domain.enums import (
    AttackOrigin,
    BodyPart,
    EventOutcome,
    EventType,
    PassType,
    PatternType,
    Period,
    PressureLevel,
    ShotOutcome,
    ShotType,
)
from domain.events.base import MatchEvent
from domain.events.defensive import DefensiveEvent
from domain.events.match_events import GoalEvent
from domain.events.offensive import CarryEvent, PassEvent, ShotEvent
from domain.match.match import MatchContext, Player, Team

SIMULATOR_VERSION = "1.0"
SIMULATION_NAMESPACE = uuid5(NAMESPACE_URL, "squeeze.simulator")
SIMULATION_EPOCH = datetime(2026, 8, 15, 15, 0, tzinfo=UTC)


class ScenarioExpectation(DomainModel):
    expected_patterns: list[PatternType]
    expected_consequences: list[str]


class ScenarioBundle(DomainModel):
    scenario: str
    seed: int
    context: MatchContext
    events: list[MatchEvent]
    expectation: ScenarioExpectation


def _clock(total_second: int) -> MatchClock:
    minute, second = divmod(total_second, 60)
    return MatchClock(period=Period.SECOND_HALF if minute >= 45 else Period.FIRST_HALF, minute=minute, second=second)


def _stable_uuid(*parts: object) -> UUID:
    return uuid5(SIMULATION_NAMESPACE, ":".join(str(part) for part in parts))


def _teams_players(scenario: str, seed: int) -> tuple[Team, Team, list[Player]]:
    blue = Team(
        team_id=_stable_uuid(scenario, seed, "team", "blue"),
        name="Blue FC",
        short_name="BLUE",
    )
    red = Team(
        team_id=_stable_uuid(scenario, seed, "team", "red"),
        name="Red FC",
        short_name="RED",
    )
    players: list[Player] = []
    for i in range(1, 12):
        players.append(
            Player(
                player_id=_stable_uuid(scenario, seed, "player", "blue", i),
                team_id=blue.team_id,
                name=f"Blue {i}",
                shirt_number=i,
                position="MID" if i < 8 else "FWD",
            )
        )
        players.append(
            Player(
                player_id=_stable_uuid(scenario, seed, "player", "red", i),
                team_id=red.team_id,
                name=f"Red {i}",
                shirt_number=i,
                position="MID" if i < 8 else "FWD",
            )
        )
    return blue, red, players


def _base_context(scenario: str, seed: int) -> MatchContext:
    blue, red, players = _teams_players(scenario, seed)
    return MatchContext.create(blue, red, players).model_copy(
        update={
            "match_id": _stable_uuid(scenario, seed, "match"),
            "current_clock": _clock(3300),
            "period": Period.SECOND_HALF,
        }
    )


def _p(context: MatchContext, team: UUID, shirt: int) -> UUID:
    return next(player.player_id for player in context.players_on_pitch if player.team_id == team and player.shirt_number == shirt)


def _event_context(origin: AttackOrigin = AttackOrigin.OPEN_PLAY, pressure: PressureLevel = PressureLevel.NONE) -> EventContext:
    return EventContext(attack_origin=origin, pressure_level=pressure, body_part=BodyPart.RIGHT_FOOT)


def _ambient_possession(context: MatchContext, rng: random.Random, start_second: int, count: int) -> list[MatchEvent]:
    events: list[MatchEvent] = []
    blue = context.home_team.team_id
    red = context.away_team.team_id
    for idx in range(count):
        second = start_second + idx * (5 + rng.randint(0, 5))
        if idx % 2 == 0:
            sender = _p(context, red, 6 + (idx % 4))
            recipient = _p(context, red, 7 + (idx % 4))
            x = 0.41 + rng.random() * 0.10
            y = 0.25 + rng.random() * 0.40
            events.append(
                PassEvent(
                    match_id=context.match_id,
                    sequence=idx + 1,
                    match_clock=_clock(second),
                    period=Period.SECOND_HALF,
                    team_id=red,
                    player_id=sender,
                    location=Location(x=x, y=y),
                    end_location=Location(x=min(0.72, x + 0.08), y=min(0.78, y + 0.08)),
                    outcome=EventOutcome.COMPLETE,
                    pass_type=PassType.SIMPLE,
                    recipient_id=recipient,
                    distance=10,
                    pressure_level=PressureLevel.LOW,
                    context=_event_context(AttackOrigin.OPEN_PLAY, PressureLevel.LOW),
                )
            )
        else:
            player = _p(context, blue, 5 + (idx % 5))
            x = 0.52 + rng.random() * 0.18
            y = 0.32 + rng.random() * 0.24
            events.append(
                CarryEvent(
                    match_id=context.match_id,
                    sequence=idx + 1,
                    match_clock=_clock(second),
                    period=Period.SECOND_HALF,
                    team_id=blue,
                    player_id=player,
                    location=Location(x=x, y=y),
                    start_location=Location(x=x - 0.04, y=y - 0.02),
                    end_location=Location(x=min(0.82, x + 0.11), y=min(0.72, y + 0.07)),
                    outcome=EventOutcome.SUCCESS,
                    distance=12,
                    pressure_level=PressureLevel.MEDIUM,
                    defender_count=2,
                    context=_event_context(AttackOrigin.OPEN_PLAY, PressureLevel.MEDIUM),
                )
            )
    return events


def _press_counter_goal(context: MatchContext, rng: random.Random) -> list[MatchEvent]:
    match_id = context.match_id
    blue = context.home_team.team_id
    red = context.away_team.team_id
    events: list[MatchEvent] = []
    seq = 1

    def add(event: MatchEvent) -> None:
        nonlocal seq
        event.sequence = seq
        seq += 1
        events.append(event)

    # Balanced red circulation gives a baseline before the squeeze.
    for offset in range(0, 80, 14):
        x = 0.38 + rng.random() * 0.05
        add(PassEvent(match_id=match_id, sequence=seq, match_clock=_clock(3300 + offset), period=Period.SECOND_HALF, team_id=red, player_id=_p(context, red, 6), location=Location(x=x, y=0.42), end_location=Location(x=x + 0.04, y=0.58), outcome=EventOutcome.COMPLETE, pass_type=PassType.SIMPLE, recipient_id=_p(context, red, 8), distance=9))

    # Blue pressure wave around 55'.
    for offset, y in [(96, 0.22), (104, 0.46), (112, 0.71), (121, 0.36), (130, 0.62)]:
        add(DefensiveEvent(match_id=match_id, sequence=seq, match_clock=_clock(3300 + offset), period=Period.SECOND_HALF, event_type=EventType.PRESSURE, team_id=blue, player_id=_p(context, blue, 7), location=Location(x=0.72, y=y), outcome=EventOutcome.SUCCESS, context=_event_context(pressure=PressureLevel.HIGH), forced_turnover=False))
    for offset, y in [(136, 0.41), (151, 0.32), (166, 0.57)]:
        add(DefensiveEvent(match_id=match_id, sequence=seq, match_clock=_clock(3300 + offset), period=Period.SECOND_HALF, event_type=EventType.RECOVERY, team_id=blue, player_id=_p(context, blue, 8), location=Location(x=0.70, y=y), outcome=EventOutcome.WON, context=_event_context(AttackOrigin.COUNTERPRESS, PressureLevel.HIGH), forced_turnover=True))

    # Fill the quiet spell between the press wave and the turnover with open-play circulation.
    for event in _ambient_possession(context, rng, 3380, 12):
        add(event)

    # Turnover -> progressive pass -> carry -> box entry -> shot -> goal.
    start = 3480
    add(DefensiveEvent(match_id=match_id, sequence=seq, match_clock=_clock(start), period=Period.SECOND_HALF, event_type=EventType.INTERCEPTION, team_id=blue, player_id=_p(context, blue, 6), location=Location(x=0.53, y=0.51), outcome=EventOutcome.WON, context=_event_context(AttackOrigin.TURNOVER, PressureLevel.HIGH), forced_turnover=True))
    add(PassEvent(match_id=match_id, sequence=seq, match_clock=_clock(start + 2), period=Period.SECOND_HALF, team_id=blue, player_id=_p(context, blue, 6), location=Location(x=0.54, y=0.50), end_location=Location(x=0.72, y=0.34), outcome=EventOutcome.COMPLETE, pass_type=PassType.THROUGH_BALL, recipient_id=_p(context, blue, 10), distance=24, pressure_level=PressureLevel.MEDIUM, context=_event_context(AttackOrigin.TURNOVER, PressureLevel.MEDIUM)))
    add(CarryEvent(match_id=match_id, sequence=seq, match_clock=_clock(start + 5), period=Period.SECOND_HALF, team_id=blue, player_id=_p(context, blue, 10), location=Location(x=0.73, y=0.34), start_location=Location(x=0.73, y=0.34), end_location=Location(x=0.86, y=0.41), outcome=EventOutcome.SUCCESS, distance=16, pressure_level=PressureLevel.MEDIUM, defender_count=2, context=_event_context(AttackOrigin.TURNOVER, PressureLevel.MEDIUM)))
    add(ShotEvent(match_id=match_id, sequence=seq, match_clock=_clock(start + 9), period=Period.SECOND_HALF, team_id=blue, player_id=_p(context, blue, 9), location=Location(x=0.90, y=0.48), outcome=EventOutcome.SUCCESS, shot_type=ShotType.OPEN_PLAY, shot_outcome=ShotOutcome.GOAL, target_zone="LOW_RIGHT", distance=10, angle=88, pressure_level=PressureLevel.LOW, assist_provider_id=_p(context, blue, 10), context=_event_context(AttackOrigin.TURNOVER, PressureLevel.LOW)))
    add(GoalEvent(match_id=match_id, sequence=seq, match_clock=_clock(start + 10), period=Period.SECOND_HALF, team_id=blue, player_id=_p(context, blue, 9), location=Location(x=1.0, y=0.5), outcome=EventOutcome.SUCCESS, assist_player_id=_p(context, blue, 10)))
    return events


def _counterattack(context: MatchContext, rng: random.Random) -> list[MatchEvent]:
    bundle = _press_counter_goal(context, rng)
    return bundle[-5:]


def _high_press(context: MatchContext, rng: random.Random) -> list[MatchEvent]:
    return _press_counter_goal(context, rng)[:14]


def _half_space(context: MatchContext, _rng: random.Random) -> list[MatchEvent]:
    blue = context.home_team.team_id
    match_id = context.match_id
    events: list[MatchEvent] = []
    for i, x in enumerate([0.64, 0.70, 0.78, 0.86], start=1):
        events.append(PassEvent(match_id=match_id, sequence=i, match_clock=_clock(3600 + i * 5), period=Period.SECOND_HALF, team_id=blue, player_id=_p(context, blue, 10), location=Location(x=x, y=0.34), end_location=Location(x=min(0.93, x + 0.08), y=0.35), outcome=EventOutcome.COMPLETE, pass_type=PassType.SIMPLE, recipient_id=_p(context, blue, 11), distance=10))
    return events


def _control_without_threat(context: MatchContext, _rng: random.Random) -> list[MatchEvent]:
    blue = context.home_team.team_id
    match_id = context.match_id
    events: list[MatchEvent] = []
    for i in range(12):
        x = 0.55 + (i % 4) * 0.04
        events.append(PassEvent(match_id=match_id, sequence=i + 1, match_clock=_clock(3300 + i * 12), period=Period.SECOND_HALF, team_id=blue, player_id=_p(context, blue, 6), location=Location(x=x, y=0.25 + (i % 3) * 0.2), end_location=Location(x=min(0.73, x + 0.05), y=0.32 + (i % 3) * 0.15), outcome=EventOutcome.COMPLETE, pass_type=PassType.SIMPLE, recipient_id=_p(context, blue, 8), distance=8))
    return events


def _player_takeover(context: MatchContext, _rng: random.Random) -> list[MatchEvent]:
    blue = context.home_team.team_id
    match_id = context.match_id
    events: list[MatchEvent] = []
    for i in range(7):
        x = 0.42 + i * 0.055
        events.append(CarryEvent(match_id=match_id, sequence=i + 1, match_clock=_clock(3540 + i * 6), period=Period.SECOND_HALF, team_id=blue, player_id=_p(context, blue, 10), location=Location(x=x, y=0.34), start_location=Location(x=x, y=0.34), end_location=Location(x=min(0.88, x + 0.11), y=0.35), outcome=EventOutcome.SUCCESS, distance=13, pressure_level=PressureLevel.MEDIUM, defender_count=1))
    events.append(ShotEvent(match_id=match_id, sequence=8, match_clock=_clock(3585), period=Period.SECOND_HALF, team_id=blue, player_id=_p(context, blue, 10), location=Location(x=0.88, y=0.48), outcome=EventOutcome.SUCCESS, shot_type=ShotType.OPEN_PLAY, shot_outcome=ShotOutcome.ON_TARGET, target_zone="HIGH_LEFT", distance=13, angle=84, pressure_level=PressureLevel.MEDIUM))
    return events


def _momentum_shift(context: MatchContext, rng: random.Random) -> list[MatchEvent]:
    return _control_without_threat(context, rng)[:4] + _press_counter_goal(context, rng)[4:]


SCENARIOS = {
    "normal_open_play": _control_without_threat,
    "high_press": _high_press,
    "counterattack": _counterattack,
    "half_space_exploitation": _half_space,
    "control_without_threat": _control_without_threat,
    "player_takeover": _player_takeover,
    "momentum_shift": _momentum_shift,
    "press_counter_goal": _press_counter_goal,
}

EXPECTATIONS = {
    "high_press": ScenarioExpectation(expected_patterns=[PatternType.HIGH_PRESS], expected_consequences=["TURNOVER"]),
    "counterattack": ScenarioExpectation(expected_patterns=[PatternType.COUNTERATTACK], expected_consequences=["SHOT"]),
    "half_space_exploitation": ScenarioExpectation(expected_patterns=[PatternType.HALF_SPACE_EXPLOITATION], expected_consequences=["BOX_ENTRY"]),
    "control_without_threat": ScenarioExpectation(expected_patterns=[PatternType.CONTROL_WITHOUT_THREAT], expected_consequences=["TERRITORY_GAIN"]),
    "player_takeover": ScenarioExpectation(expected_patterns=[PatternType.PLAYER_INFLUENCE], expected_consequences=["TERRITORY_GAIN"]),
    "momentum_shift": ScenarioExpectation(expected_patterns=[PatternType.PRESSURE_SHIFT], expected_consequences=["TERRITORY_GAIN"]),
    "press_counter_goal": ScenarioExpectation(expected_patterns=[PatternType.HIGH_PRESS, PatternType.PRESSURE_SHIFT, PatternType.COUNTERATTACK], expected_consequences=["SHOT", "GOAL"]),
    "normal_open_play": ScenarioExpectation(expected_patterns=[], expected_consequences=[]),
}


def generate_scenario(name: str, seed: int = 42) -> ScenarioBundle:
    if name not in SCENARIOS:
        raise ValueError(f"Unknown scenario {name}. Available: {', '.join(SCENARIOS)}")
    context = _base_context(name, seed)
    rng = random.Random(seed)
    events = SCENARIOS[name](context, rng)
    for event in events:
        event.event_id = _stable_uuid(name, seed, "event", event.sequence)
        event.timestamp = SIMULATION_EPOCH + timedelta(seconds=event.match_clock.total_seconds())
        event.source = "squeeze-simulator"
        event.schema_version = "1.0"
    return ScenarioBundle(
        scenario=name,
        seed=seed,
        context=context,
        events=events,
        expectation=EXPECTATIONS[name],
    )
