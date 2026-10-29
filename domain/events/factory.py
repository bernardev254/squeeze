from __future__ import annotations

from domain.enums import EventType
from domain.events.base import MatchEvent
from domain.events.defensive import DefensiveEvent
from domain.events.match_events import CardEvent, GoalEvent, MatchRefereeEvent, SubstitutionEvent
from domain.events.offensive import CarryEvent, PassEvent, ShotEvent
from domain.events.set_piece import SetPieceEvent

EventUnion = (
    PassEvent
    | CarryEvent
    | ShotEvent
    | DefensiveEvent
    | SetPieceEvent
    | CardEvent
    | GoalEvent
    | SubstitutionEvent
    | MatchRefereeEvent
    | MatchEvent
)


def parse_event(data: dict) -> EventUnion:
    event_type = data.get("event_type")
    event_type = EventType(event_type) if isinstance(event_type, str) else event_type
    if event_type == EventType.PASS:
        return PassEvent.model_validate(data)
    if event_type == EventType.CARRY:
        return CarryEvent.model_validate(data)
    if event_type == EventType.SHOT:
        return ShotEvent.model_validate(data)
    if event_type in {EventType.TACKLE, EventType.INTERCEPTION, EventType.BLOCK, EventType.CLEARANCE, EventType.RECOVERY, EventType.PRESSURE}:
        return DefensiveEvent.model_validate(data)
    if event_type in {EventType.CORNER, EventType.FREE_KICK, EventType.THROW_IN}:
        return SetPieceEvent.model_validate(data)
    if event_type == EventType.GOAL:
        return GoalEvent.model_validate(data)
    if event_type == EventType.CARD:
        return CardEvent.model_validate(data)
    if event_type == EventType.SUBSTITUTION:
        return SubstitutionEvent.model_validate(data)
    if event_type in {EventType.FOUL, EventType.PENALTY_AWARDED, EventType.PENALTY_KICK, EventType.OFFSIDE}:
        return MatchRefereeEvent.model_validate(data)
    return MatchEvent.model_validate(data)
