from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import Field, computed_field

from domain.common import DomainModel
from domain.insights.evidence import EvidenceRef


class InsightCandidate(DomainModel):
    candidate_id: UUID = Field(default_factory=uuid4)
    pattern_id: UUID
    significance: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    novelty: float = Field(ge=0.0, le=1.0)
    recency: float = Field(ge=0.0, le=1.0)
    audience_relevance: float = Field(ge=0.0, le=1.0)
    action_impact: float = Field(default=0.0, ge=0.0, le=1.0)
    consequence_magnitude: float = Field(default=0.0, ge=0.0, le=1.0)
    deduplication_key: str
    evidence: list[EvidenceRef]

    @computed_field
    @property
    def priority_score(self) -> float:
        return round(
            self.significance
            * self.confidence
            * self.novelty
            * self.recency
            * self.audience_relevance
            * (1.0 + self.action_impact * 0.2 + self.consequence_magnitude * 0.15),
            3,
        )
