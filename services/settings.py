from __future__ import annotations

import os

from pydantic import Field

from domain.common import DomainModel


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _env_first(*names: str, default: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


class AppSettings(DomainModel):
    app_env: str = Field(default_factory=lambda: os.getenv("APP_ENV", "production"))
    azure_environment: str = Field(default_factory=lambda: os.getenv("AZURE_ENVIRONMENT", "production"))
    log_level: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    api_host: str = Field(default_factory=lambda: os.getenv("API_HOST", "127.0.0.1"))
    api_port: int = Field(default_factory=lambda: int(os.getenv("API_PORT", "8000")))


class AgentSettings(DomainModel):
    gateway_enabled: bool = Field(default_factory=lambda: _env_bool("AGENT_GATEWAY_ENABLED", True))
    fallback_enabled: bool = Field(default_factory=lambda: _env_bool("AGENT_FALLBACK_ENABLED", True))
    max_concurrency: int = Field(default_factory=lambda: int(os.getenv("AGENT_MAX_CONCURRENCY", "4")))
    timeout_seconds: int = Field(default_factory=lambda: int(os.getenv("AGENT_TIMEOUT_SECONDS", "10")))
    max_retries: int = Field(default_factory=lambda: int(os.getenv("AGENT_MAX_RETRIES", "2")))
    cooldown_seconds: int = Field(default_factory=lambda: int(os.getenv("AGENT_COOLDOWN_SECONDS", "30")))
    temperature: float = Field(default_factory=lambda: float(os.getenv("AGENT_TEMPERATURE", "0")))
    max_tokens: int | None = Field(
        default_factory=lambda: int(os.environ["AGENT_MAX_TOKENS"])
        if os.getenv("AGENT_MAX_TOKENS")
        else None
    )
    analyst_enabled: bool = Field(default_factory=lambda: _env_bool("ANALYST_ENABLED", True))
    explanation_enabled: bool = Field(default_factory=lambda: _env_bool("EXPLANATION_ENABLED", True))
    validator_enabled: bool = Field(default_factory=lambda: _env_bool("VALIDATOR_AGENT_ENABLED", True))
    narrative_enabled: bool = Field(default_factory=lambda: _env_bool("NARRATIVE_ENABLED", True))
    personalization_enabled: bool = Field(default_factory=lambda: _env_bool("PERSONALIZATION_ENABLED", False))
    narrative_batch_seconds: float = Field(
        default_factory=lambda: float(os.getenv("NARRATIVE_BATCH_SECONDS", "5"))
    )


class AzureSettings(DomainModel):
    tenant_id: str | None = Field(default_factory=lambda: os.getenv("AZURE_TENANT_ID") or None)
    client_id: str | None = Field(default_factory=lambda: os.getenv("AZURE_CLIENT_ID") or None)
    client_secret: str | None = Field(default_factory=lambda: os.getenv("AZURE_CLIENT_SECRET") or None)
    subscription_id: str | None = Field(default_factory=lambda: os.getenv("AZURE_SUBSCRIPTION_ID") or None)
    resource_group: str | None = Field(default_factory=lambda: os.getenv("AZURE_RESOURCE_GROUP") or None)
    region: str | None = Field(default_factory=lambda: os.getenv("AZURE_REGION") or None)
    use_managed_identity: bool = Field(
        default_factory=lambda: _env_bool("AZURE_USE_MANAGED_IDENTITY", False)
    )


class FoundrySettings(DomainModel):
    project_endpoint: str | None = Field(
        default_factory=lambda: os.getenv("FOUNDRY_PROJECT_ENDPOINT")
        or os.getenv("AZURE_FOUNDRY_PROJECT_ENDPOINT")
        or None
    )
    project_name: str | None = Field(
        default_factory=lambda: os.getenv("AZURE_FOUNDRY_PROJECT_NAME") or None
    )
    analyst_agent_id: str | None = Field(
        default_factory=lambda: _env_first(
            "FOUNDRY_AGENT_ID_ANALYST",
            "ANALYST_AGENT_ID",
            default="",
        )
        or None
    )
    explanation_agent_id: str | None = Field(
        default_factory=lambda: _env_first(
            "FOUNDRY_AGENT_ID_EXPLANATION",
            "EXPLANATION_AGENT_ID",
            default="",
        )
        or None
    )
    validator_agent_id: str | None = Field(
        default_factory=lambda: _env_first(
            "FOUNDRY_AGENT_ID_VALIDATOR",
            "VALIDATOR_AGENT_ID",
            default="",
        )
        or None
    )
    narrative_agent_id: str | None = Field(
        default_factory=lambda: _env_first(
            "FOUNDRY_AGENT_ID_NARRATIVE",
            "NARRATIVE_AGENT_ID",
            default="",
        )
        or None
    )
    personalization_agent_id: str = Field(
        default_factory=lambda: os.getenv("PERSONALIZATION_AGENT_ID", "")
    )


class ObservabilitySettings(DomainModel):
    tracing_enabled: bool = Field(default_factory=lambda: _env_bool("AGENT_TRACING_ENABLED", True))
    trace_payloads: bool = Field(default_factory=lambda: _env_bool("AGENT_TRACE_PAYLOADS", False))
    metrics_enabled: bool = Field(default_factory=lambda: _env_bool("AGENT_METRICS_ENABLED", True))
    token_usage_enabled: bool = Field(
        default_factory=lambda: _env_bool("AGENT_TOKEN_USAGE_ENABLED", True)
    )


class EvaluationSettings(DomainModel):
    run_azure_integration_tests: bool = Field(
        default_factory=lambda: _env_bool("RUN_AZURE_INTEGRATION_TESTS", False)
    )


class EventStreamSettings(DomainModel):
    event_hub_namespace: str | None = Field(default_factory=lambda: os.getenv("SQUEEZE_EVENT_HUB_NAMESPACE", os.getenv("EVENT_HUB_NAMESPACE", "")) or None)
    event_hub_name: str = Field(default_factory=lambda: os.getenv("SQUEEZE_EVENT_HUB_NAME", os.getenv("EVENT_HUB_NAME", "squeeze-events")))
    consumer_group: str = Field(
        default_factory=lambda: os.getenv("SQUEEZE_EVENT_HUB_CONSUMER_GROUP")
        or os.getenv("EVENT_HUB_CONSUMER_GROUP")
        or "$Default"
    )
    connection_string: str | None = Field(
        default_factory=lambda: os.getenv("SQUEEZE_EVENT_HUB_CONNECTION_STRING", os.getenv("EVENT_HUB_CONNECTION_STRING", "")) or None
    )
    dead_letter_name: str = Field(
        default_factory=lambda: os.getenv("SQUEEZE_EVENT_HUB_DEAD_LETTER_NAME", os.getenv("EVENT_HUB_DEAD_LETTER_NAME", "squeeze-deadletter"))
    )
    checkpoint_store: str | None = Field(
        default_factory=lambda: os.getenv("SQUEEZE_EVENT_HUB_CHECKPOINT_STORE", os.getenv("EVENT_HUB_CHECKPOINT_STORE", "")) or None
    )
    batch_size: int = Field(default_factory=lambda: int(os.getenv("SQUEEZE_EVENT_HUB_BATCH_SIZE", "100")))
    retry_total: int = Field(default_factory=lambda: int(os.getenv("SQUEEZE_EVENT_HUB_RETRY_TOTAL", "3")))


class LiveFeedSettings(DomainModel):
    scenario: str = Field(default_factory=lambda: os.getenv("LIVE_FEED_SCENARIO", "press_counter_goal"))
    seed: int = Field(default_factory=lambda: int(os.getenv("LIVE_FEED_SEED", "42")))
    speed: int = Field(default_factory=lambda: int(os.getenv("LIVE_FEED_SPEED", "10")))
    min_delay_ms: int = Field(default_factory=lambda: int(os.getenv("LIVE_FEED_MIN_DELAY_MS", "500")))
    max_delay_ms: int = Field(default_factory=lambda: int(os.getenv("LIVE_FEED_MAX_DELAY_MS", "4000")))
    loop: bool = Field(default_factory=lambda: _env_bool("LIVE_FEED_LOOP", False))
    match_id: str | None = Field(default_factory=lambda: os.getenv("LIVE_FEED_MATCH_ID") or None)


class DashboardStreamSettings(DomainModel):
    enabled: bool = Field(
        default_factory=lambda: _env_bool("SQUEEZE_DASHBOARD_STREAM_ENABLED", False)
    )
    consumer_group: str = Field(
        default_factory=lambda: os.getenv("SQUEEZE_DASHBOARD_CONSUMER_GROUP", "$Default")
    )
    starting_position: str = Field(
        default_factory=lambda: os.getenv("SQUEEZE_DASHBOARD_STARTING_POSITION", "@latest")
    )


class CloudStateSettings(DomainModel):
    snapshot_interval_events: int = Field(
        default_factory=lambda: int(os.getenv("SNAPSHOT_INTERVAL_EVENTS", "50"))
    )


class CostControlSettings(DomainModel):
    enabled: bool = Field(default_factory=lambda: _env_bool("CLOUD_COST_CONTROLS_ENABLED", True))
    max_agent_invocations_per_match: int | None = Field(
        default_factory=lambda: int(os.environ["MAX_AGENT_INVOCATIONS_PER_MATCH"])
        if os.getenv("MAX_AGENT_INVOCATIONS_PER_MATCH")
        else None
    )
    max_event_retention_days: int = Field(
        default_factory=lambda: int(os.getenv("MAX_EVENT_RETENTION_DAYS", "7"))
    )
    max_trace_retention_days: int = Field(
        default_factory=lambda: int(os.getenv("MAX_TRACE_RETENTION_DAYS", "7"))
    )


class ScalingSettings(DomainModel):
    processor_min_replicas: int = Field(
        default_factory=lambda: int(os.getenv("PROCESSOR_MIN_REPLICAS", "0"))
    )
    processor_max_replicas: int = Field(
        default_factory=lambda: int(os.getenv("PROCESSOR_MAX_REPLICAS", "5"))
    )
    eventhub_target_unprocessed_events: int = Field(
        default_factory=lambda: int(os.getenv("EVENTHUB_TARGET_UNPROCESSED_EVENTS", "100"))
    )
    keda_polling_interval_seconds: int = Field(
        default_factory=lambda: int(os.getenv("KEDA_POLLING_INTERVAL_SECONDS", "30"))
    )
    keda_cooldown_seconds: int = Field(
        default_factory=lambda: int(os.getenv("KEDA_COOLDOWN_SECONDS", "300"))
    )


class Settings(DomainModel):
    app: AppSettings = Field(default_factory=AppSettings)
    agents: AgentSettings = Field(default_factory=AgentSettings)
    azure: AzureSettings = Field(default_factory=AzureSettings)
    foundry: FoundrySettings = Field(default_factory=FoundrySettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    evaluation: EvaluationSettings = Field(default_factory=EvaluationSettings)
    event_stream: EventStreamSettings = Field(default_factory=EventStreamSettings)
    live_feed: LiveFeedSettings = Field(default_factory=LiveFeedSettings)
    dashboard_stream: DashboardStreamSettings = Field(default_factory=DashboardStreamSettings)
    cloud_state: CloudStateSettings = Field(default_factory=CloudStateSettings)
    cost_controls: CostControlSettings = Field(default_factory=CostControlSettings)
    scaling: ScalingSettings = Field(default_factory=ScalingSettings)

    def require_production_configuration(self) -> None:
        if not self.foundry.project_endpoint:
            raise ValueError("Microsoft Foundry requires FOUNDRY_PROJECT_ENDPOINT")
        required_agents = [
            self.foundry.analyst_agent_id if self.agents.analyst_enabled else None,
            self.foundry.explanation_agent_id if self.agents.explanation_enabled else None,
            self.foundry.validator_agent_id if self.agents.validator_enabled else None,
            self.foundry.narrative_agent_id if self.agents.narrative_enabled else None,
        ]
        if any(not agent_id for agent_id in required_agents):
            raise ValueError("Microsoft Foundry requires configured agent IDs for enabled agents")
        if not (self.event_stream.connection_string or self.event_stream.event_hub_namespace):
            raise ValueError("Azure Event Hubs requires SQUEEZE_EVENT_HUB_NAMESPACE or SQUEEZE_EVENT_HUB_CONNECTION_STRING")


def load_settings() -> Settings:
    settings = Settings()
    settings.require_production_configuration()
    return settings
