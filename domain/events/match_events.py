from __future__ import annotations

from uuid import UUID

from domain.enums import EventType
from domain.events.base import MatchEvent


class MatchRefereeEvent(MatchEvent):
    event_type: EventType


class CardEvent(MatchEvent):
    event_type: EventType = EventType.CARD
    card_type: str
    reason: str


class SubstitutionEvent(MatchEvent):
    event_type: EventType = EventType.SUBSTITUTION
    player_in: UUID
    player_out: UUID


class GoalEvent(MatchEvent):
    event_type: EventType = EventType.GOAL
    goal_type: str = "OPEN_PLAY"
    assist_player_id: UUID | None = None

