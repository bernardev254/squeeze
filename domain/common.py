from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from domain.enums import (
    AttackOrigin,
    BodyPart,
    GameState,
    Period,
    PitchChannel,
    PitchThird,
    PitchZone,
    PressureLevel,
    TagCode,
    TagSource,
)


class DomainModel(BaseModel):
    model_config = ConfigDict(use_enum_values=False, arbitrary_types_allowed=False)


class MatchClock(DomainModel):
    period: Period
    minute: int = Field(ge=0)
    second: int = Field(ge=0, le=59)
    stoppage_seconds: int = Field(default=0, ge=0)

    def total_seconds(self) -> int:
        base = (self.minute * 60) + self.second + self.stoppage_seconds
        period_offset = {
            Period.FIRST_HALF: 0,
            Period.SECOND_HALF: 45 * 60,
            Period.EXTRA_TIME_FIRST: 90 * 60,
            Period.EXTRA_TIME_SECOND: 105 * 60,
        }[self.period]
        return max(base, period_offset)

    def display(self) -> str:
        if self.stoppage_seconds:
            stoppage_minute, stoppage_second = divmod(self.stoppage_seconds, 60)
            return f"{self.minute}+{stoppage_minute}:{stoppage_second:02d}"
        return f"{self.minute}:{self.second:02d}"

    def __lt__(self, other: MatchClock) -> bool:
        return self.total_seconds() < other.total_seconds()


class SpatialConfig(DomainModel):
    final_third_x: float = 2 / 3
    defensive_third_x: float = 1 / 3
    box_x: float = 0.84
    box_y_min: float = 0.21
    box_y_max: float = 0.79
    danger_x: float = 0.88
    danger_y_min: float = 0.34
    danger_y_max: float = 0.66
    channel_breaks: tuple[float, float, float, float] = (0.18, 0.38, 0.62, 0.82)


DEFAULT_SPATIAL_CONFIG = SpatialConfig()


class Location(DomainModel):
    """Normalized attacking orientation: x 0.0 is own goal, x 1.0 is opponent goal."""

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    zone: PitchZone | None = None
    third: PitchThird | None = None
    channel: PitchChannel | None = None
    in_penalty_area: bool = False
    behind_defensive_line: bool = False
    between_lines: bool = False

    @field_validator("zone", mode="before")
    @classmethod
    def _none_zone(cls, value: Any) -> Any:
        return value

    def classified(self, config: SpatialConfig = DEFAULT_SPATIAL_CONFIG) -> Location:
        third = (
            PitchThird.DEFENSIVE
            if self.x < config.defensive_third_x
            else PitchThird.FINAL
            if self.x >= config.final_third_x
            else PitchThird.MIDDLE
        )
        b1, b2, b3, b4 = config.channel_breaks
        channel = (
            PitchChannel.WIDE_LEFT
            if self.y < b1
            else PitchChannel.HALF_SPACE_LEFT
            if self.y < b2
            else PitchChannel.CENTER
            if self.y <= b3
            else PitchChannel.HALF_SPACE_RIGHT
            if self.y <= b4
            else PitchChannel.WIDE_RIGHT
        )
        in_box = self.x >= config.box_x and config.box_y_min <= self.y <= config.box_y_max
        in_danger = self.x >= config.danger_x and config.danger_y_min <= self.y <= config.danger_y_max
        zone = (
            PitchZone.DANGER_AREA
            if in_danger
            else PitchZone.BOX
            if in_box
            else PitchZone.FINAL_THIRD
            if third == PitchThird.FINAL
            else PitchZone.MIDDLE_THIRD
            if third == PitchThird.MIDDLE
            else PitchZone.DEFENSIVE_THIRD
        )
        return self.model_copy(
            update={
                "zone": zone,
                "third": third,
                "channel": channel,
                "in_penalty_area": in_box,
                "behind_defensive_line": self.x >= 0.82,
                "between_lines": 0.58 <= self.x < 0.82,
            }
        )


class EventTag(DomainModel):
    code: TagCode
    source: TagSource
    confidence: float = Field(ge=0.0, le=1.0)


class Scoreline(DomainModel):
    home: int = Field(ge=0)
    away: int = Field(ge=0)

    def game_state(self) -> GameState:
        if self.home > self.away:
            return GameState.HOME_LEADING
        if self.away > self.home:
            return GameState.AWAY_LEADING
        return GameState.DRAW

    def goal_difference(self, home_team: bool) -> int:
        return self.home - self.away if home_team else self.away - self.home


class EventContext(DomainModel):
    pressure_level: PressureLevel = PressureLevel.NONE
    body_part: BodyPart | None = None
    attack_origin: AttackOrigin = AttackOrigin.OPEN_PLAY
    possession_id: UUID | None = None
    sequence_id: UUID | None = None
    scoreline: Scoreline | None = None
    game_state: GameState | None = None


class TimeWindow(DomainModel):
    start: MatchClock
    end: MatchClock

    @computed_field
    @property
    def duration_seconds(self) -> int:
        return max(0, self.end.total_seconds() - self.start.total_seconds())


class MetricValue(DomainModel):
    name: str
    team_id: UUID | None = None
    player_id: UUID | None = None
    value: float
    previous: float | None = None


class StateChange(DomainModel):
    dimension: str
    before: float
    after: float
    delta: float
    timestamp: MatchClock


def new_id() -> UUID:
    return uuid4()


def utc_now() -> datetime:
    return datetime.now(UTC)
