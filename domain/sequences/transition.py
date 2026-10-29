from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import Field

from domain.common import DomainModel, Location


class TransitionSequence(DomainModel):
    transition_id: UUID = Field(default_factory=uuid4)
    winning_team_id: UUID
    trigger_event_id: UUID
    recovery_location: Location
    progression_time_seconds: float
    territory_gain: float
    final_third_entry: bool = False
    box_entry: bool = False
    shot: bool = False
    chance: bool = False
    goal: bool = False

