from __future__ import annotations

from uuid import UUID

from pydantic import Field

from domain.common import DomainModel, MatchClock


class TeamState(DomainModel):
    team_id: UUID
    control: float = Field(ge=0.0, le=1.0)
    pressure: float = Field(ge=0.0, le=1.0)
    threat: float = Field(ge=0.0, le=1.0)
    territory: float = Field(ge=0.0, le=1.0)
    tempo: float = Field(ge=0.0, le=1.0)
    transition_intensity: float = Field(ge=0.0, le=1.0)
    attacking_intensity: float = Field(ge=0.0, le=1.0)
    defensive_stability: float = Field(ge=0.0, le=1.0)
    action_impact: float = Field(default=0.0, ge=-1.0, le=1.0)


class MatchState(DomainModel):
    timestamp: MatchClock
    home: TeamState
    away: TeamState
    dominant_team_id: UUID | None
    state_labels: list[str] = Field(default_factory=list)
    momentum_direction: UUID | None = None
    momentum_strength: float = Field(ge=0.0, le=1.0)
    chaos: float = Field(ge=0.0, le=1.0)
