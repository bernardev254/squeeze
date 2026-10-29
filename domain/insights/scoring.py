from __future__ import annotations

from domain.insights.candidate import InsightCandidate


def score_candidate(candidate: InsightCandidate) -> float:
    return candidate.priority_score

