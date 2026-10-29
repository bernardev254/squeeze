from __future__ import annotations

from uuid import UUID

from domain.agents.context import (
    AnalystContext,
    ExplanationContext,
    NarrativeContext,
    ValidatorContext,
)
from domain.causal.model import CausalChain
from domain.enums import Audience
from domain.events.base import MatchEvent
from domain.insights.evidence import EvidenceRef
from domain.insights.insight import Insight
from domain.metrics.impact import ActionImpact
from domain.patterns.base import Pattern
from services.match_engine.processor import MatchProcessor


class AgentContextBuilder:
    def __init__(self, processor: MatchProcessor) -> None:
        self.processor = processor

    def analyst_context(self, insight_id: UUID) -> AnalystContext:
        insight, pattern = self._insight_and_pattern(insight_id)
        chain = self._chain_for_pattern(pattern.pattern_id)
        return AnalystContext(
            match=self.processor.context,
            current_state=self.processor.state,
            pattern_candidate=pattern,
            evidence=pattern.evidence,
            action_impacts=self._impacts_for_evidence(pattern.evidence)[-8:],
            causal_chain=chain,
            recent_events=self._events_for_evidence(pattern.evidence)[-8:],
            relevant_sequences=self.processor.attacks[-3:],
        )

    def explanation_context(self, insight_id: UUID) -> ExplanationContext:
        insight, pattern = self._insight_and_pattern(insight_id)
        chain = self._chain_for_pattern(pattern.pattern_id)
        return ExplanationContext(
            match=self.processor.context,
            validated_pattern=pattern,
            evidence=insight.evidence,
            action_impacts=self._impacts_for_evidence(insight.evidence)[-8:],
            causal_chain=chain,
            consequences=[consequence.value for consequence in insight.consequences],
        )

    def validator_context(self, insight_id: UUID) -> ValidatorContext:
        insight, pattern = self._insight_and_pattern(insight_id)
        claim = next(claim for claim in self.processor.claims if claim.pattern_id == pattern.pattern_id)
        return ValidatorContext(
            claim=claim,
            evidence=claim.evidence,
            underlying_events=self._events_for_evidence(claim.evidence)[-12:],
            action_impacts=self._impacts_for_evidence(claim.evidence)[-12:],
            metrics=self.processor.metrics,
            pattern=pattern,
            causal_chain=self._chain_for_pattern(pattern.pattern_id),
        )

    def narrative_context(
        self,
        insight_id: UUID,
        audience: Audience = Audience.FAN,
    ) -> NarrativeContext:
        insight = next(item for item in self.processor.insights if item.insight_id == insight_id)
        return NarrativeContext(
            insight=insight,
            audience=audience,
            available_evidence=insight.evidence,
        )

    def _insight_and_pattern(self, insight_id: UUID) -> tuple[Insight, Pattern]:
        insight = next(item for item in self.processor.insights if item.insight_id == insight_id)
        pattern = next(item for item in self.processor.patterns if item.pattern_id == insight.pattern_id)
        return insight, pattern

    def _chain_for_pattern(self, pattern_id: UUID) -> CausalChain | None:
        return next(
            (chain for chain in self.processor.causal_chains if chain.pattern_id == pattern_id),
            None,
        )

    def _events_for_evidence(self, evidence: list[EvidenceRef]) -> list[MatchEvent]:
        event_ids = {event_id for item in evidence for event_id in item.event_ids}
        return [event for event in self.processor.events if event.event_id in event_ids]

    def _impacts_for_evidence(self, evidence: list[EvidenceRef]) -> list[ActionImpact]:
        event_ids = {event_id for item in evidence for event_id in item.event_ids}
        return [impact for impact in self.processor.action_impacts if impact.event_id in event_ids]
