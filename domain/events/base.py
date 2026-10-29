from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from domain.common import DomainModel, EventContext, EventTag, Location, MatchClock, utc_now
from domain.enums import EventOutcome, EventType, Period


class MatchEvent(DomainModel):
    event_id: UUID = Field(default_factory=uuid4)
    match_id: UUID
    sequence: int = Field(ge=0)
    timestamp: datetime = Field(default_factory=utc_now)
    match_clock: MatchClock
    period: Period
    event_type: EventType
    team_id: UUID
    player_id: UUID | None = None
    location: Location
    outcome: EventOutcome = EventOutcome.NONE
    context: EventContext = Field(default_factory=EventContext)
    related_player_id: UUID | None = None
    source: str = "synthetic"
    schema_version: str = "1.0"
    tags: list[EventTag] = Field(default_factory=list)

    @model_validator(mode="after")
    def classify_location(self) -> MatchEvent:
        self.location = self.location.classified()
        return self

