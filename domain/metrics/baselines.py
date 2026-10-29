from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from domain.common import DomainModel, TimeWindow


class BaselineType(StrEnum):
    PREVIOUS_EQUIVALENT_WINDOW = "PREVIOUS_EQUIVALENT_WINDOW"
    ROLLING_AVERAGE = "ROLLING_AVERAGE"
    MATCH_TO_DATE = "MATCH_TO_DATE"
    TEAM_BASELINE = "TEAM_BASELINE"
    PLAYER_BASELINE = "PLAYER_BASELINE"
    OPPONENT_BASELINE = "OPPONENT_BASELINE"


class Baseline(DomainModel):
    baseline_type: BaselineType
    metric: str
    team_id: UUID | None = None
    player_id: UUID | None = None
    value: float
    window: TimeWindow | None = None
    sample_size: int = 0


class WindowComparison(DomainModel):
    metric: str
    current_window: TimeWindow
    previous_window: TimeWindow
    current: float
    previous: float
    delta: float
    percentage_change: float | None
    baselines: list[Baseline] = Field(default_factory=list)

    @classmethod
    def compare(
        cls,
        metric: str,
        current_window: TimeWindow,
        previous_window: TimeWindow,
        current: float,
        previous: float,
    ) -> WindowComparison:
        percentage_change = None if previous == 0 else (current - previous) / abs(previous)
        return cls(
            metric=metric,
            current_window=current_window,
            previous_window=previous_window,
            current=current,
            previous=previous,
            delta=current - previous,
            percentage_change=percentage_change,
        )

