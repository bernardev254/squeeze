from __future__ import annotations

from domain.common import Location
from domain.enums import EventOutcome, EventType
from domain.events.base import MatchEvent


class SetPieceEvent(MatchEvent):
    event_type: EventType
    delivery_location: Location | None = None
    delivery_outcome: EventOutcome = EventOutcome.NONE

