from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import Field

from domain.common import DomainModel, Location, MatchClock
from domain.enums import PossessionEndReason


class PossessionChain(DomainModel):
    possession_id: UUID = Field(default_factory=uuid4)
    match_id: UUID
    team_id: UUID
    start_time: MatchClock
    end_time: MatchClock | None = None
    start_location: Location
    end_location: Location
    event_ids: list[UUID] = Field(default_factory=list)
    duration_seconds: float = 0.0
    event_count: int = 0
    territory_gain: float = 0.0
    progression_distance: float = 0.0
    final_third_entries: int = 0
    box_entries: int = 0
    shots: int = 0
    chances: int = 0
    end_reason: PossessionEndReason | None = None

