from __future__ import annotations

from enum import StrEnum

from domain.common import DomainModel


class WindowSize(StrEnum):
    THIRTY_SECONDS = "30s"
    TWO_MINUTES = "2m"
    FIVE_MINUTES = "5m"
    TEN_MINUTES = "10m"
    MATCH_TO_DATE = "match"


WINDOW_SECONDS = {
    WindowSize.THIRTY_SECONDS: 30,
    WindowSize.TWO_MINUTES: 120,
    WindowSize.FIVE_MINUTES: 300,
    WindowSize.TEN_MINUTES: 600,
    WindowSize.MATCH_TO_DATE: 10_000,
}


class RollingWindow(DomainModel):
    size: WindowSize
    end_second: int

    @property
    def start_second(self) -> int:
        return max(0, self.end_second - WINDOW_SECONDS[self.size])

    def contains(self, second: int) -> bool:
        return self.start_second <= second <= self.end_second

    def previous(self) -> RollingWindow:
        span = WINDOW_SECONDS[self.size]
        return RollingWindow(size=self.size, end_second=max(0, self.end_second - span))

