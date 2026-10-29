from __future__ import annotations

import json
from abc import ABC, abstractmethod
from time import perf_counter
from typing import Any, cast

from pydantic import BaseModel

from domain.agents.gateway import (
    AgentClaim,
    AgentRequest,
    AgentResponse,
    AnalystOutput,
    ExplanationOutput,
    NarrativeOutput,
    TokenUsage,
    ValidatorAgentOutput,
)
from domain.enums import AgentRole, AgentStatus, Audience
from services.settings import Settings


class AgentGateway(ABC):
    @abstractmethod
    def invoke(self, request: AgentRequest) -> AgentResponse:
        ...

    def invoke_structured(self, request: AgentRequest) -> AgentResponse:
        return self.invoke(request)

    @abstractmethod
    def health(self) -> dict[str, str | bool | list[str]]:
        ...


class AzureFoundryAgentGateway(AgentGateway):
    def __init__(
        self,
        settings: Settings | None = None,
        project_client: Any | None = None,
    ) -> None:
        self.settings = settings or Settings()
        if not self.settings.foundry.project_endpoint:
            raise ValueError("Azure Foundry endpoint is required for azure mode")
        self.project_client = project_client or self._project_client()

    def invoke(self, request: AgentRequest) -> AgentResponse:
        started = perf_counter()
        try:
            output_text, metadata = self._invoke_foundry(request)
            output, claims = self._structured_output(request, output_text)
            status = AgentStatus.SUCCEEDED
            errors: list[str] = []
            fallback_used = False
        except TimeoutError as exc:
            output, claims, metadata, errors, status, fallback_used = self._failure(
                "timeout",
                exc,
                request,
            )
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            output, claims, metadata, errors, status, fallback_used = self._failure(
                "schema_validation_failure",
                exc,
                request,
            )
        except Exception as exc:
            output, claims, metadata, errors, status, fallback_used = self._failure(
                "provider_unavailable",
                exc,
                request,
            )
        latency_ms = round((perf_counter() - started) * 1000, 3)
        usage = metadata.pop("usage", None)
        token_usage = _token_usage_from(usage)
        return AgentResponse(
            invocation_id=request.invocation_id,
            agent_id=request.agent_id,
            agent_role=request.agent_role,
            status=status,
            output=output,
            structured_claims=claims,
            confidence=output.get("confidence") if isinstance(output.get("confidence"), float) else None,
            model_metadata=metadata,
            latency_ms=latency_ms,
            token_usage=token_usage,
            errors=errors,
            fallback_used=fallback_used,
        )

    def health(self) -> dict[str, str | bool | list[str]]:
        return {
            "agent_gateway": "AzureFoundryAgentGateway",
            "ai_provider": "microsoft-foundry",
            "available_agents": [role.value for role in AgentRole],
            "fallback_enabled": self.settings.agents.fallback_enabled,
            "configured": bool(self.settings.foundry.project_endpoint),
        }

    def _project_client(self) -> Any:
        try:
            from azure.ai.projects import AIProjectClient
            from azure.identity import DefaultAzureCredential
        except ImportError as exc:
            raise ValueError(
                "Foundry mode requires azure-ai-projects and azure-identity. "
                "Install the cloud extra before starting SQUEEZE."
            ) from exc
        if not self.settings.foundry.project_endpoint:
            raise ValueError("Microsoft Foundry requires FOUNDRY_PROJECT_ENDPOINT")
        return AIProjectClient(
            endpoint=self.settings.foundry.project_endpoint,
            credential=DefaultAzureCredential(),
            allow_preview=True,
        )

    def _invoke_foundry(self, request: AgentRequest) -> tuple[str, dict[str, Any]]:
        openai_client = self.project_client.get_openai_client(agent_name=request.agent_id)
        conversation = openai_client.conversations.create()
        response = openai_client.responses.create(
            conversation=conversation.id,
            input=_foundry_input(request),
            timeout=request.timeout_seconds,
        )
        output_text = str(getattr(response, "output_text", "") or "")
        if not output_text:
            raise ValueError("Foundry response did not include output_text")
        metadata: dict[str, Any] = {
            "provider": "azure-foundry",
            "model": str(getattr(response, "model", "") or "foundry-agent"),
            "provider_request_id": str(getattr(response, "id", "") or ""),
            "agent_name": request.agent_id,
        }
        usage = getattr(response, "usage", None)
        if usage is not None:
            metadata["usage"] = usage
        return output_text, metadata

    def _structured_output(
        self,
        request: AgentRequest,
        output_text: str,
    ) -> tuple[dict, list[AgentClaim]]:
        payload = _json_payload(output_text)
        model = cast(type[BaseModel] | None, {
            AgentRole.ANALYST: AnalystOutput,
            AgentRole.EXPLANATION: ExplanationOutput,
            AgentRole.VALIDATOR: ValidatorAgentOutput,
            AgentRole.NARRATIVE: NarrativeOutput,
        }.get(request.agent_role))
        if model is None:
            return payload, []
        if request.agent_role == AgentRole.NARRATIVE:
            payload = _normalise_narrative_output(payload)
        parsed = model.model_validate(payload)
        claims = list(getattr(parsed, "claims", []) or [])
        return parsed.model_dump(mode="json"), claims

    def _failure(
        self,
        reason: str,
        exc: Exception,
        request: AgentRequest,
    ) -> tuple[dict, list[AgentClaim], dict[str, Any], list[str], AgentStatus, bool]:
        return (
            {
                "message": "Foundry explanation unavailable; deterministic fallback used.",
                "reason": reason,
            },
            [],
            {
                "provider": "azure-foundry",
                "model": "foundry-agent",
                "agent_name": request.agent_id,
                "failure_reason": reason,
            },
            [f"{reason}: {exc}"],
            AgentStatus.FALLBACK,
            True,
        )


def gateway_from_settings(settings: Settings) -> AgentGateway:
    return AzureFoundryAgentGateway(settings)


def _foundry_input(request: AgentRequest) -> str:
    return json.dumps(
        {
            "instructions": [
                "You are a SQUEEZE football intelligence agent.",
                "The supplied deterministic context is authoritative.",
                "Do not calculate metrics, action impact, score, match clock, possession, or xG.",
                "Do not invent events, evidence, players, teams, numbers, or causal links.",
                "Return only valid JSON matching the requested output schema.",
            ],
            "agent_role": request.agent_role.value,
            "requested_output_schema": request.requested_output_schema,
            "prompt_version": request.prompt_version,
            "context": request.context,
        },
        sort_keys=True,
        default=str,
    )


def _json_payload(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Foundry structured response must be a JSON object")
    return payload


def _normalise_narrative_output(payload: dict) -> dict:
    """Accept concise model copy while preserving its text as an agent narrative."""
    normalised = dict(payload)
    normalised.setdefault("confidence", 0.7)
    if normalised.get("narratives"):
        return normalised
    text = str(normalised.get("narrative") or normalised.get("headline") or "").strip()
    if not text:
        return normalised
    confidence = float(normalised["confidence"])
    normalised["narratives"] = [
        {
            "audience": audience.value,
            "text": text,
            "confidence": confidence,
        }
        for audience in Audience
    ]
    return normalised


def _token_usage_from(value: Any) -> TokenUsage | None:
    if value is None:
        return None
    if isinstance(value, dict):
        input_tokens = int(value.get("input_tokens") or value.get("prompt_tokens") or 0)
        output_tokens = int(value.get("output_tokens") or value.get("completion_tokens") or 0)
        total_tokens = int(value.get("total_tokens") or input_tokens + output_tokens)
        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )
    input_tokens = int(getattr(value, "input_tokens", getattr(value, "prompt_tokens", 0)) or 0)
    output_tokens = int(getattr(value, "output_tokens", getattr(value, "completion_tokens", 0)) or 0)
    total_tokens = int(getattr(value, "total_tokens", input_tokens + output_tokens) or 0)
    return TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens)
