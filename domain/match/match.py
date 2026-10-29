from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import Field

from domain.common import DomainModel, MatchClock, Scoreline
from domain.enums import GameState, Period


class Team(DomainModel):
    team_id: UUID = Field(default_factory=uuid4)
    name: str
    short_name: str


class Player(DomainModel):
    player_id: UUID = Field(default_factory=uuid4)
    team_id: UUID
    name: str
    shirt_number: int = Field(ge=1, le=99)
    position: str


class Formation(DomainModel):
    team_id: UUID
    shape: str


class MatchContext(DomainModel):
    match_id: UUID
    home_team: Team
    away_team: Team
    current_score: Scoreline
    period: Period
    current_clock: MatchClock
    possession_team_id: UUID | None = None
    formations: list[Formation] = Field(default_factory=list)
    players_on_pitch: list[Player] = Field(default_factory=list)
    game_state: GameState

    @classmethod
    def create(cls, home_team: Team, away_team: Team, players: list[Player]) -> MatchContext:
        clock = MatchClock(period=Period.FIRST_HALF, minute=0, second=0)
        score = Scoreline(home=0, away=0)
        return cls(
            match_id=uuid4(),
            home_team=home_team,
            away_team=away_team,
            current_score=score,
            period=Period.FIRST_HALF,
            current_clock=clock,
            players_on_pitch=players,
            formations=[
                Formation(team_id=home_team.team_id, shape="4-3-3"),
                Formation(team_id=away_team.team_id, shape="4-2-3-1"),
            ],
            game_state=score.game_state(),
        )

    def is_home(self, team_id: UUID) -> bool:
        return team_id == self.home_team.team_id

    def leading(self, team_id: UUID) -> bool:
        return self.goal_difference(team_id) > 0

    def trailing(self, team_id: UUID) -> bool:
        return self.goal_difference(team_id) < 0

    def drawing(self) -> bool:
        return self.current_score.home == self.current_score.away

    def goal_difference(self, team_id: UUID) -> int:
        return self.current_score.goal_difference(self.is_home(team_id))

    def with_score_goal_for(self, team_id: UUID) -> MatchContext:
        score = (
            Scoreline(home=self.current_score.home + 1, away=self.current_score.away)
            if self.is_home(team_id)
            else Scoreline(home=self.current_score.home, away=self.current_score.away + 1)
        )
        return self.model_copy(update={"current_score": score, "game_state": score.game_state()})


class Match(DomainModel):
    context: MatchContext

