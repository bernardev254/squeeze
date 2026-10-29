from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field

from domain.common import DomainModel, utc_now
from domain.enums import AgentClaimType, AgentRole, AgentStatus, Audience, FallbackReason


class PromptVersion(DomainModel):
    name: str
    version: str
    purpose: str
    input_schema: str
    output_schema: str
    safety_rules: list[str] = Field(default_factory=list)


class AgentContextVersion(DomainModel):
    context_version: str = "agent-context.v1"
    schema_version: str = "agent-schema.v1"


class AgentClaim(DomainModel):
    claim_id: UUID = Field(default_factory=uuid4)
    claim_type: AgentClaimType
    text: str
    evidence_ids: list[UUID] = Field(default_factory=list)
    metric_refs: list[str] = Field(default_factory=list)
    event_refs: list[UUID] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = "agent"
    supported: bool = True


class TokenUsage(DomainModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class AgentRequest(DomainModel):
    invocation_id: UUID = Field(default_factory=uuid4)
    agent_id: str
    agent_role: AgentRole
    match_id: UUID
    insight_id: UUID | None = None
    context: dict
    context_version: str = "agent-context.v1"
    prompt_version: str = "prompt.v1"
    requested_output_schema: str
    priority: str = "P1"
    timeout_seconds: int = 10
    metadata: dict[str, str] = Field(default_factory=dict)


class AnalystOutput(DomainModel):
    summary: str
    observed_change: str
    affected_team: str
    affected_player: str | None = None
    supporting_evidence_ids: list[UUID] = Field(default_factory=list)
    claims: list[AgentClaim] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty: str = ""
    unsupported_information: list[str] = Field(default_factory=list)


class ExplanationOutput(DomainModel):
    observed_facts: list[str] = Field(default_factory=list)
    interpretation: str
    why_it_matters: str
    causal_steps: list[str] = Field(default_factory=list)
    claims: list[AgentClaim] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    unsupported_information: list[str] = Field(default_factory=list)


class ValidatorAgentOutput(DomainModel):
    valid: bool
    supported_claim_ids: list[UUID] = Field(default_factory=list)
    rejected_claim_ids: list[UUID] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class AudienceNarrative(DomainModel):
    audience: Audience
    text: str
    evidence_ids: list[UUID] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class NarrativeOutput(DomainModel):
    narratives: list[AudienceNarrative] = Field(default_factory=list)
    claims: list[AgentClaim] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    unsupported_information: list[str] = Field(default_factory=list)


class AgentResponse(DomainModel):
    invocation_id: UUID
    agent_id: str
    agent_role: AgentRole
    status: AgentStatus
    output: dict
    structured_claims: list[AgentClaim] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    model_metadata: dict[str, str] = Field(default_factory=dict)
    latency_ms: float = 0.0
    token_usage: TokenUsage | None = None
    errors: list[str] = Field(default_factory=list)
    fallback_used: bool = False
    timestamp: datetime = Field(default_factory=utc_now)


class AgentInvocation(DomainModel):
    trace_id: UUID = Field(default_factory=uuid4)
    span_id: UUID = Field(default_factory=uuid4)
    invocation_id: UUID
    match_id: UUID
    insight_id: UUID | None
    agent_id: str
    agent_role: AgentRole
    agent_version: str = "foundry-agent.v1"
    prompt_version: str
    context_version: str
    model: str | None = None
    provider: str | None = None
    provider_request_id: str | None = None
    candidate_id: UUID | None = None
    pattern_id: UUID | None = None
    context_hash: str | None = None
    start_time: datetime
    end_time: datetime
    latency_ms: float
    status: AgentStatus
    retry_count: int = 0
    fallback_used: bool = False
    fallback_reason: FallbackReason | None = None
    validation_result: str | None = None
    error: str | None = None
    token_usage: TokenUsage | None = None


class AgentTrace(DomainModel):
    trace_id: UUID = Field(default_factory=uuid4)
    insight_id: UUID | None = None
    invocations: list[AgentInvocation] = Field(default_factory=list)
    claims: list[AgentClaim] = Field(default_factory=list)
    narratives: list[AudienceNarrative] = Field(default_factory=list)
    fallback_used: bool = False
    fallback_reason: FallbackReason | None = None
