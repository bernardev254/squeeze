from __future__ import annotations

from domain.enums import EventType, TackleOutcome
from domain.events.base import MatchEvent


class DefensiveEvent(MatchEvent):
    event_type: EventType
    tackle_outcome: TackleOutcome | None = None
    foul_committed: bool = False
    forced_turnover: bool = False

