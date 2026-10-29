from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID

from domain.agents.gateway import (
    AgentInvocation,
    AgentRequest,
    AgentResponse,
    AgentTrace,
    AudienceNarrative,
    NarrativeOutput,
)
from domain.common import DomainModel, utc_now
from domain.enums import AgentRole, AgentStatus, Audience, FallbackReason
from domain.insights.insight import AudienceRepresentations
from services.agents.gateway import AgentGateway, gateway_from_settings
from services.insight_engine.context_builder import AgentContextBuilder
from services.match_engine.processor import MatchProcessor
from services.settings import Settings, load_settings


class AgentOrchestrationResult(DomainModel):
    insight_id: UUID
    trace: AgentTrace
    responses: list[AgentResponse]
    narratives: list[AudienceNarrative]
    fallback_used: bool = False
    fallback_reason: FallbackReason | None = None


class AgentTelemetry(DomainModel):
    agent_invocations: int = 0
    fallbacks: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0


class AgentOrchestrator:
    def __init__(
        self,
        processor: MatchProcessor,
        settings: Settings | None = None,
        gateway: AgentGateway | None = None,
    ) -> None:
        self.processor = processor
        self.settings = settings or load_settings()
        self.gateway = gateway or gateway_from_settings(self.settings)
        self.context_builder = AgentContextBuilder(processor)
        self.traces: dict[UUID, AgentTrace] = {}
        self.responses: dict[UUID, AgentResponse] = {}
        self.telemetry = AgentTelemetry()
        self._last_invoked_by_key: dict[str, int] = {}

    def status(self) -> dict[str, str | bool | list[str]]:
        return self.gateway.health()

    def invoke_for_insight(self, insight_id: UUID) -> AgentOrchestrationResult:
        insight = next(item for item in self.processor.insights if item.insight_id == insight_id)
        pattern = next(item for item in self.processor.patterns if item.pattern_id == insight.pattern_id)
        if not self._should_invoke(pattern.deduplication_key, pattern.detected_at.total_seconds()):
            trace = AgentTrace(insight_id=insight_id, fallback_used=True, fallback_reason=FallbackReason.DISABLED)
            self.traces[insight_id] = trace
            return AgentOrchestrationResult(
                insight_id=insight_id,
                trace=trace,
                responses=[],
                narratives=[],
                fallback_used=True,
                fallback_reason=FallbackReason.DISABLED,
            )
        requests = self._requests_for_insight(insight_id)
        responses: list[AgentResponse] = []
        invocations: list[AgentInvocation] = []
        fallback_used = False
        fallback_reason: FallbackReason | None = None
        for request in requests:
            started = utc_now()
            response = self.gateway.invoke_structured(request)
            ended = utc_now()
            responses.append(response)
            self.responses[response.invocation_id] = response
            if response.fallback_used or response.status != AgentStatus.SUCCEEDED:
                fallback_used = True
                fallback_reason = FallbackReason.PROVIDER_UNAVAILABLE
            invocations.append(self._invocation_from(request, response, started, ended, fallback_reason))
            self._update_telemetry(response)
        narratives = self._narratives_from(responses)
        if not narratives:
            fallback_used = True
            fallback_reason = fallback_reason or FallbackReason.UNSUPPORTED_CLAIM
            narratives = self._fallback_narratives(insight_id)
        trace = AgentTrace(
            insight_id=insight_id,
            invocations=invocations,
            claims=[claim for response in responses for claim in response.structured_claims],
            narratives=narratives,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )
        self.traces[insight_id] = trace
        self._last_invoked_by_key[pattern.deduplication_key] = pattern.detected_at.total_seconds()
        return AgentOrchestrationResult(
            insight_id=insight_id,
            trace=trace,
            responses=responses,
            narratives=narratives,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )

    def invoke_narrative_for_insight(self, insight_id: UUID) -> AgentOrchestrationResult:
        """Generate audience copy without running the analyst, explanation, or validator agents."""
        request = self._request(
            AgentRole.NARRATIVE,
            _required_agent_id(self.settings.foundry.narrative_agent_id, AgentRole.NARRATIVE),
            self.processor.context.match_id,
            insight_id,
            self.context_builder.narrative_context(insight_id).model_dump(mode="json"),
            "NarrativeOutput",
            "P2",
        )
        started = utc_now()
        response = self.gateway.invoke_structured(request)
        ended = utc_now()
        self.responses[response.invocation_id] = response
        narratives = self._narratives_from([response])
        fallback_used = response.fallback_used or not narratives
        fallback_reason = FallbackReason.PROVIDER_UNAVAILABLE if fallback_used else None
        if not narratives:
            narratives = self._fallback_narratives(insight_id)
        trace = AgentTrace(
            insight_id=insight_id,
            invocations=[self._invocation_from(request, response, started, ended, fallback_reason)],
            claims=response.structured_claims,
            narratives=narratives,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )
        self.traces[insight_id] = trace
        self._update_telemetry(response)
        return AgentOrchestrationResult(
            insight_id=insight_id,
            trace=trace,
            responses=[response],
            narratives=narratives,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )

    def _requests_for_insight(self, insight_id: UUID) -> list[AgentRequest]:
        match_id = self.processor.context.match_id
        requests: list[AgentRequest] = []
        if self.settings.agents.analyst_enabled:
            requests.append(
                self._request(
                    AgentRole.ANALYST,
                    _required_agent_id(self.settings.foundry.analyst_agent_id, AgentRole.ANALYST),
                    match_id,
                    insight_id,
                    self.context_builder.analyst_context(insight_id).model_dump(mode="json"),
                    "AnalystOutput",
                    "P1",
                )
            )
        if self.settings.agents.explanation_enabled:
            requests.append(
                self._request(
                    AgentRole.EXPLANATION,
                    _required_agent_id(self.settings.foundry.explanation_agent_id, AgentRole.EXPLANATION),
                    match_id,
                    insight_id,
                    self.context_builder.explanation_context(insight_id).model_dump(mode="json"),
                    "ExplanationOutput",
                    "P1",
                )
            )
        if self.settings.agents.validator_enabled:
            requests.append(
                self._request(
                    AgentRole.VALIDATOR,
                    _required_agent_id(self.settings.foundry.validator_agent_id, AgentRole.VALIDATOR),
                    match_id,
                    insight_id,
                    self.context_builder.validator_context(insight_id).model_dump(mode="json"),
                    "ValidatorAgentOutput",
                    "P1",
                )
            )
        if self.settings.agents.narrative_enabled:
            requests.append(
                self._request(
                    AgentRole.NARRATIVE,
                    _required_agent_id(self.settings.foundry.narrative_agent_id, AgentRole.NARRATIVE),
                    match_id,
                    insight_id,
                    self.context_builder.narrative_context(insight_id).model_dump(mode="json"),
                    "NarrativeOutput",
                    "P2",
                )
            )
        return requests

    def _request(
        self,
        role: AgentRole,
        agent_id: str,
        match_id: UUID,
        insight_id: UUID,
        context: dict,
        output_schema: str,
        priority: str,
    ) -> AgentRequest:
        insight = next((item for item in self.processor.insights if item.insight_id == insight_id), None)
        pattern_id = str(insight.pattern_id) if insight else ""
        candidate_id = str(insight.candidate_id) if insight and insight.candidate_id else ""
        return AgentRequest(
            agent_id=agent_id,
            agent_role=role,
            match_id=match_id,
            insight_id=insight_id,
            context=context,
            prompt_version=f"{role.value.lower()}.v1",
            requested_output_schema=output_schema,
            priority=priority,
            timeout_seconds=self.settings.agents.timeout_seconds,
            metadata={
                "schema_version": "agent-schema.v1",
                "context_hash": _stable_context_hash(context),
                "pattern_id": pattern_id,
                "candidate_id": candidate_id,
            },
        )

    def _should_invoke(self, key: str, current_second: int) -> bool:
        previous = self._last_invoked_by_key.get(key)
        if previous is None:
            return True
        return current_second - previous >= self.settings.agents.cooldown_seconds

    def _invocation_from(
        self,
        request: AgentRequest,
        response: AgentResponse,
        started: datetime,
        ended: datetime,
        fallback_reason: FallbackReason | None,
    ) -> AgentInvocation:
        return AgentInvocation(
            invocation_id=request.invocation_id,
            match_id=request.match_id,
            insight_id=request.insight_id,
            agent_id=request.agent_id,
            agent_role=request.agent_role,
            prompt_version=request.prompt_version,
            context_version=request.context_version,
            model=response.model_metadata.get("model"),
            provider=response.model_metadata.get("provider"),
            provider_request_id=response.model_metadata.get("provider_request_id"),
            candidate_id=_uuid_or_none(request.metadata.get("candidate_id")),
            pattern_id=_uuid_or_none(request.metadata.get("pattern_id")),
            context_hash=request.metadata.get("context_hash"),
            start_time=started,
            end_time=ended,
            latency_ms=response.latency_ms,
            status=response.status,
            fallback_used=response.fallback_used,
            fallback_reason=fallback_reason,
            validation_result=response.status.value,
            error="; ".join(response.errors) if response.errors else None,
            token_usage=response.token_usage,
        )

    def _narratives_from(self, responses: list[AgentResponse]) -> list[AudienceNarrative]:
        narratives: list[AudienceNarrative] = []
        for response in responses:
            if response.agent_role != AgentRole.NARRATIVE or response.status != AgentStatus.SUCCEEDED:
                continue
            output = NarrativeOutput.model_validate(response.output)
            narratives.extend(output.narratives)
        return narratives

    def _fallback_narratives(self, insight_id: UUID) -> list[AudienceNarrative]:
        insight = next(item for item in self.processor.insights if item.insight_id == insight_id)
        representation = self.processor.representations.get(insight_id)
        if representation is None:
            return [
                AudienceNarrative(
                    audience=audience,
                    text=insight.explanation,
                    evidence_ids=[e.evidence_id for e in insight.evidence],
                    confidence=insight.confidence,
                )
                for audience in Audience
            ]
        return _narratives_from_representation(representation, insight.confidence)

    def _update_telemetry(self, response: AgentResponse) -> None:
        self.telemetry.agent_invocations += 1
        self.telemetry.latency_ms = round(self.telemetry.latency_ms + response.latency_ms, 3)
        self.telemetry.fallbacks += int(response.fallback_used)
        if response.token_usage:
            self.telemetry.input_tokens += response.token_usage.input_tokens
            self.telemetry.output_tokens += response.token_usage.output_tokens
            self.telemetry.total_tokens += response.token_usage.total_tokens


def _narratives_from_representation(
    representation: AudienceRepresentations,
    confidence: float,
) -> list[AudienceNarrative]:
    return [
        AudienceNarrative(audience=Audience.FAN, text=representation.fan.text, confidence=confidence),
        AudienceNarrative(
            audience=Audience.COMMENTATOR,
            text=representation.commentator.text,
            confidence=confidence,
        ),
        AudienceNarrative(
            audience=Audience.STUDIO,
            text=f"{representation.studio.headline}: {' | '.join(representation.studio.lines)}",
            confidence=confidence,
        ),
        AudienceNarrative(
            audience=Audience.OVERLAY,
            text=f"{representation.overlay.headline} {representation.overlay.stat}",
            confidence=confidence,
        ),
    ]


def _stable_context_hash(context: dict) -> str:
    encoded = json.dumps(context, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _uuid_or_none(value: str | None) -> UUID | None:
    if not value:
        return None
    return UUID(value)


def _required_agent_id(value: str | None, role: AgentRole) -> str:
    if not value:
        raise ValueError(f"Foundry agent ID is required for {role.value}")
    return value
