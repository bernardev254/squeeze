from __future__ import annotations

from uuid import UUID

from pydantic import Field

from domain.common import Location
from domain.enums import (
    BodyPart,
    EventOutcome,
    EventType,
    PassType,
    PressureLevel,
    ShotOutcome,
    ShotType,
)
from domain.events.base import MatchEvent


class PassEvent(MatchEvent):
    event_type: EventType = EventType.PASS
    pass_type: PassType = PassType.SIMPLE
    recipient_id: UUID | None = None
    end_location: Location
    distance: float = Field(ge=0.0)
    pressure_level: PressureLevel = PressureLevel.NONE
    body_part: BodyPart = BodyPart.RIGHT_FOOT
    progressive: bool = False


class CarryEvent(MatchEvent):
    event_type: EventType = EventType.CARRY
    start_location: Location
    end_location: Location
    distance: float = Field(ge=0.0)
    dribble_outcome: EventOutcome = EventOutcome.SUCCESS
    pressure_level: PressureLevel = PressureLevel.NONE
    defender_count: int = Field(default=0, ge=0)


class ShotEvent(MatchEvent):
    event_type: EventType = EventType.SHOT
    shot_type: ShotType = ShotType.OPEN_PLAY
    shot_outcome: ShotOutcome
    target_zone: str = "CENTER"
    distance: float = Field(ge=0.0)
    angle: float = Field(ge=0.0, le=180.0)
    pressure_level: PressureLevel = PressureLevel.NONE
    body_part: BodyPart = BodyPart.RIGHT_FOOT
    assist_provider_id: UUID | None = None
    shot_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    shot_quality_factors: list[str] = Field(default_factory=list)

