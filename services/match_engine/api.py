from __future__ import annotations

from pathlib import Path
from threading import Lock, Thread
from time import sleep, time
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from domain.enums import AgentRole, AgentStatus, Audience
from services.agents.orchestrator import AgentOrchestrator
from services.agents.prompts import PromptRegistry
from services.insight_engine.context_builder import AgentContextBuilder
from services.match_engine.live_bridge import LiveRuntimeBridge
from services.match_engine.processor import MatchProcessor, ProcessingResult
from services.settings import Settings, load_settings
from services.streaming.azure_event_hubs import AzureEventHubEventStream
from simulator.runner import MatchSimulator
from simulator.scenarios import generate_scenario
from simulator.sinks import AzureEventHubSink

STATIC_DIR = Path(__file__).resolve().parents[2] / "apps" / "explorer" / "static"


class Runtime:
    processor: MatchProcessor | None = None
    orchestrator: AgentOrchestrator | None = None
    results: list[ProcessingResult] = []
    bridge: LiveRuntimeBridge | None = None
    simulation: Thread | None = None
    simulation_status: dict[str, object] = {"state": "idle"}
    agent_narratives: dict[str, dict[str, str]] = {}
    narrative_status: dict[str, dict[str, str]] = {}
    narrative_lock: Lock = Lock()


runtime = Runtime()


app = FastAPI(title="SQUEEZE Match Engine")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _schedule_startup_simulation() -> None:
    if runtime.simulation is not None and runtime.simulation.is_alive():
        return
    try:
        settings = load_settings()
    except ValueError:
        return
    if settings.app.app_env not in {"development", "local", "test"}:
        return
    if runtime.bridge is None or not runtime.bridge.status().get("connected"):
        return

    runtime.simulation_status = {
        "state": "queued",
        "scenario": "press_counter_goal",
        "speed": 2.5,
        "seed": int(time()),
    }
    runtime.simulation = Thread(
        target=_publish_simulation,
        args=("press_counter_goal", int(time()), 2.5),
        name="squeeze-dev-bootstrap-simulator",
        daemon=True,
    )
    runtime.simulation.start()


@app.on_event("startup")
def start_live_dashboard_bridge() -> None:
    if not Settings().dashboard_stream.enabled:
        return
    settings = load_settings()
    runtime.bridge = LiveRuntimeBridge(settings, _update_live_runtime)
    runtime.bridge.start()
    Thread(
        target=lambda: (sleep(2), _schedule_startup_simulation()),
        name="squeeze-startup-bootstrap",
        daemon=True,
    ).start()


@app.on_event("shutdown")
def stop_live_dashboard_bridge() -> None:
    if runtime.bridge is not None:
        runtime.bridge.stop()


def _update_live_runtime(result: ProcessingResult, processor: object) -> None:
    if not isinstance(processor, MatchProcessor):
        return
    if runtime.processor is not None and runtime.processor.context.match_id != processor.context.match_id:
        runtime.orchestrator = None
        runtime.results = []
        runtime.agent_narratives = {}
        runtime.narrative_status = {}
    runtime.processor = processor
    runtime.results.append(result)
    for insight in result.insights_created:
        runtime.narrative_status[str(insight.insight_id)] = {"state": "pending", "source": "agent"}
        Thread(
            target=_generate_agent_narrative,
            args=(processor, insight.insight_id),
            name=f"squeeze-narrative-{insight.insight_id}",
            daemon=True,
        ).start()


def _generate_agent_narrative(processor: MatchProcessor, insight_id: UUID) -> None:
    try:
        settings = load_settings()
        sleep(settings.agents.narrative_batch_seconds)
        with runtime.narrative_lock:
            if runtime.processor is not processor:
                return
            orchestrator = runtime.orchestrator or AgentOrchestrator(processor, load_settings())
            runtime.orchestrator = orchestrator
            result = orchestrator.invoke_narrative_for_insight(insight_id)
            response = result.responses[0]
            if response.status != AgentStatus.SUCCEEDED or response.fallback_used:
                runtime.narrative_status[str(insight_id)] = {
                    "state": "fallback",
                    "source": "deterministic",
                }
                return
            runtime.agent_narratives[str(insight_id)] = {
                narrative.audience.value.lower(): narrative.text
                for narrative in result.narratives
            }
            runtime.narrative_status[str(insight_id)] = {
                "state": "available",
                "source": "agent",
                "provider": response.model_metadata.get("provider", "azure-foundry"),
                "model": response.model_metadata.get("model", "foundry-agent"),
            }
    except Exception:
        runtime.narrative_status[str(insight_id)] = {
            "state": "fallback",
            "source": "deterministic",
        }


@app.get("/")
def explorer() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict:
    try:
        settings = load_settings()
        configuration_error = None
    except ValueError as exc:
        settings = Settings()
        configuration_error = str(exc)
    checks = {
        "configuration_loaded": True,
        "event_hubs_configured": bool(
            settings.event_stream.connection_string or settings.event_stream.event_hub_namespace
        ),
        "foundry_configured": bool(
            settings.foundry.project_endpoint
            and settings.foundry.analyst_agent_id
            and settings.foundry.explanation_agent_id
            and settings.foundry.validator_agent_id
            and settings.foundry.narrative_agent_id
        ),
        "configuration_error": configuration_error,
    }
    return {"ready": configuration_error is None, "checks": checks}


@app.get("/api/system/status")
def system_status() -> dict:
    settings = load_settings()
    return {
        "app_env": settings.app.app_env,
        "azure_environment": settings.app.azure_environment,
        "event_source": "azure-event-hubs",
        "ai_provider": "microsoft-foundry",
        "region": settings.azure.region,
        "processing": "CLOUD",
        "dashboard_stream": runtime.bridge.status() if runtime.bridge else {"enabled": False},
    }


@app.get("/api/system/config")
def system_config() -> dict:
    settings = load_settings()
    return {
        "app_env": settings.app.app_env,
        "azure_environment": settings.app.azure_environment,
        "api_host": settings.app.api_host,
        "api_port": settings.app.api_port,
        "fallback_enabled": settings.agents.fallback_enabled,
        "event_source": "azure-event-hubs",
        "event_hub_name": settings.event_stream.event_hub_name,
        "snapshot_interval_events": settings.cloud_state.snapshot_interval_events,
        "cost_controls_enabled": settings.cost_controls.enabled,
        "processor_min_replicas": settings.scaling.processor_min_replicas,
        "processor_max_replicas": settings.scaling.processor_max_replicas,
    }


@app.get("/api/matches")
def matches() -> list[dict]:
    if not runtime.processor:
        return []
    return [runtime.processor.context.model_dump(mode="json")]


@app.get("/api/matches/{match_id}")
def match(match_id: UUID) -> dict:
    processor = _processor(match_id)
    return processor.context.model_dump(mode="json")


@app.get("/api/matches/{match_id}/events")
def events(match_id: UUID) -> list[dict]:
    return [event.model_dump(mode="json") for event in _processor(match_id).events]


@app.get("/api/matches/{match_id}/possessions")
def possessions(match_id: UUID) -> list[dict]:
    return [possession.model_dump(mode="json") for possession in _processor(match_id).possessions]


@app.get("/api/matches/{match_id}/sequences")
def sequences(match_id: UUID) -> dict[str, list[dict]]:
    processor = _processor(match_id)
    return {
        "attacks": [attack.model_dump(mode="json") for attack in processor.attacks],
        "transitions": [transition.model_dump(mode="json") for transition in processor.transitions],
    }


@app.get("/api/matches/{match_id}/metrics")
def metrics(match_id: UUID) -> dict:
    return _processor(match_id).metrics.model_dump(mode="json")


@app.get("/api/matches/{match_id}/action-impacts")
def action_impacts(match_id: UUID) -> list[dict]:
    return [impact.model_dump(mode="json") for impact in _processor(match_id).action_impacts]


@app.get("/api/matches/{match_id}/state")
def state(match_id: UUID) -> dict | None:
    processor = _processor(match_id)
    return processor.state.model_dump(mode="json") if processor.state else None


@app.get("/api/matches/{match_id}/patterns")
def patterns(match_id: UUID) -> list[dict]:
    return [pattern.model_dump(mode="json") for pattern in _processor(match_id).patterns]


@app.get("/api/matches/{match_id}/insight-candidates")
def candidates(match_id: UUID) -> list[dict]:
    return [candidate.model_dump(mode="json") for candidate in _processor(match_id).candidates]


@app.get("/api/matches/{match_id}/insights")
def insights(match_id: UUID) -> list[dict]:
    processor = _processor(match_id)
    output = []
    for insight in processor.insights:
        representation = processor.representations.get(insight.insight_id)
        output.append(
            insight.model_dump(mode="json")
            | {
                "representations": representation.model_dump(mode="json")
                if representation
                else None
            }
        )
    return output


@app.get("/api/matches/{match_id}/state-changes")
def state_changes(match_id: UUID) -> list[dict]:
    return [change.model_dump(mode="json") for change in _processor(match_id).state_changes]


@app.get("/api/matches/{match_id}/causal-chains")
def causal_chains(match_id: UUID) -> list[dict]:
    return [chain.model_dump(mode="json") for chain in _processor(match_id).causal_chains]


@app.get("/api/matches/{match_id}/claims")
def claims(match_id: UUID) -> list[dict]:
    return [claim.model_dump(mode="json") for claim in _processor(match_id).claims]


@app.get("/api/matches/{match_id}/validations")
def validations(match_id: UUID) -> list[dict]:
    return [validation.model_dump(mode="json") for validation in _processor(match_id).validations]


@app.get("/api/matches/{match_id}/telemetry")
def telemetry(match_id: UUID) -> dict:
    return _processor(match_id).telemetry.model_dump(mode="json")


@app.get("/api/matches/{match_id}/processing-traces")
def processing_traces(match_id: UUID) -> list[dict]:
    return [trace.model_dump(mode="json") for trace in _processor(match_id).processing_traces]


@app.get("/api/matches/{match_id}/snapshots")
def snapshots(match_id: UUID) -> list[dict]:
    return [snapshot.model_dump(mode="json") for snapshot in _processor(match_id).snapshots]


@app.get("/api/runtime")
def runtime_state() -> dict:
    if not runtime.processor:
        return {
            "match": None,
            "cursor": 0,
            "events_total": 0,
            "events": [],
            "intelligence_events": [],
            "results": [],
            "stream": runtime.bridge.status() if runtime.bridge else {"enabled": False},
            "simulation": runtime.simulation_status,
        }
    linked_event_ids = {
        eid
        for insight in runtime.processor.insights
        for pattern in runtime.processor.patterns
        if pattern.pattern_id == insight.pattern_id
        for evidence in getattr(pattern, "evidence", [])
        for eid in getattr(evidence, "event_ids", [])
    }
    return {
        "match": runtime.processor.context.model_dump(mode="json"),
        "cursor": len(runtime.processor.events),
        "events_total": len(runtime.processor.events),
        "playing": False,
        "events": [event.model_dump(mode="json") for event in runtime.processor.events],
        "intelligence_events": [
            event.model_dump(mode="json")
            for event in runtime.processor.events
            if event.event_id in linked_event_ids
        ],
        "possessions": [p.model_dump(mode="json") for p in runtime.processor.possessions],
        "attacks": [s.model_dump(mode="json") for s in runtime.processor.attacks],
        "metrics": runtime.processor.metrics.model_dump(mode="json"),
        "action_impacts": [impact.model_dump(mode="json") for impact in runtime.processor.action_impacts],
        "state": runtime.processor.state.model_dump(mode="json") if runtime.processor.state else None,
        "patterns": [p.model_dump(mode="json") for p in runtime.processor.patterns],
        "candidates": [c.model_dump(mode="json") for c in runtime.processor.candidates],
        "insights": [
            i.model_dump(mode="json")
            | {
                "representations": runtime.processor.representations[i.insight_id].model_dump(mode="json"),
                "agent_narratives": runtime.agent_narratives.get(str(i.insight_id), {}),
                "narrative_status": runtime.narrative_status.get(str(i.insight_id), {}),
            }
            for i in runtime.processor.insights
        ],
        "state_changes": [c.model_dump(mode="json") for c in runtime.processor.state_changes],
        "causal_chains": [c.model_dump(mode="json") for c in runtime.processor.causal_chains],
        "claims": [c.model_dump(mode="json") for c in runtime.processor.claims],
        "validations": [v.model_dump(mode="json") for v in runtime.processor.validations],
        "telemetry": runtime.processor.telemetry.model_dump(mode="json"),
        "processing_traces": [t.model_dump(mode="json") for t in runtime.processor.processing_traces],
        "agent_status": runtime.orchestrator.status() if runtime.orchestrator else None,
        "system_status": system_status(),
        "agent_traces": [
            trace.model_dump(mode="json")
            for trace in runtime.orchestrator.traces.values()
        ] if runtime.orchestrator else [],
        "agent_telemetry": runtime.orchestrator.telemetry.model_dump(mode="json")
        if runtime.orchestrator
        else None,
        "snapshots": [s.model_dump(mode="json") for s in runtime.processor.snapshots[-5:]],
        "results": [result.model_dump(mode="json") for result in runtime.results[-5:]],
        "stream": runtime.bridge.status() if runtime.bridge else {"enabled": False},
        "simulation": runtime.simulation_status,
    }


@app.post("/api/simulations/start", status_code=202)
def start_simulation(payload: dict | None = None) -> dict:
    if runtime.bridge is None or not runtime.bridge.status()["connected"]:
        raise HTTPException(status_code=503, detail="Live Event Hubs bridge is not connected")
    if runtime.simulation is not None and runtime.simulation.is_alive():
        raise HTTPException(status_code=409, detail="A live simulation is already running")

    payload = payload or {}
    scenario = str(payload.get("scenario", "press_counter_goal"))
    speed = float(payload.get("speed", 2.5))
    if speed <= 0:
        raise HTTPException(status_code=422, detail="Simulation speed must be greater than zero")
    seed = int(payload.get("seed", time()))
    runtime.simulation_status = {
        "state": "starting",
        "scenario": scenario,
        "speed": speed,
        "seed": seed,
    }
    runtime.simulation = Thread(
        target=_publish_simulation,
        args=(scenario, seed, speed),
        name="squeeze-dashboard-simulator",
        daemon=True,
    )
    runtime.simulation.start()
    return runtime.simulation_status


def _publish_simulation(scenario: str, seed: int, speed: float) -> None:
    try:
        settings = load_settings()
        bundle = generate_scenario(scenario, seed)
        runtime.simulation_status = runtime.simulation_status | {
            "state": "running",
            "match_id": str(bundle.context.match_id),
            "events_total": len(bundle.events),
        }
        sink = AzureEventHubSink(
            AzureEventHubEventStream(
                settings.event_stream.connection_string,
                settings.event_stream.event_hub_name,
                event_hub_namespace=settings.event_stream.event_hub_namespace,
                batch_size=settings.event_stream.batch_size,
                retry_total=settings.event_stream.retry_total,
            )
        )
        simulator = MatchSimulator(bundle, sink=sink, speed=speed)
        simulator.run()
        runtime.simulation_status = runtime.simulation_status | {
            "state": "completed",
            "events_published": simulator.metrics.events_published,
        }
    except Exception as exc:
        runtime.simulation_status = runtime.simulation_status | {
            "state": "failed",
            "error": str(exc),
        }


@app.get("/api/insights/{insight_id}/agent-context/analyst")
def analyst_context(insight_id: UUID) -> dict:
    return _context_builder().analyst_context(insight_id).model_dump(mode="json")


@app.get("/api/insights/{insight_id}/agent-context/explanation")
def explanation_context(insight_id: UUID) -> dict:
    return _context_builder().explanation_context(insight_id).model_dump(mode="json")


@app.get("/api/insights/{insight_id}/agent-context/validator")
def validator_context(insight_id: UUID) -> dict:
    return _context_builder().validator_context(insight_id).model_dump(mode="json")


@app.get("/api/insights/{insight_id}/agent-context/narrative")
def narrative_context(insight_id: UUID, audience: Audience = Audience.FAN) -> dict:
    return _context_builder().narrative_context(insight_id, audience).model_dump(mode="json")


@app.get("/api/agents/status")
def agent_status() -> dict:
    if runtime.processor is None:
        settings = load_settings()
        return {
            "agent_gateway": "AzureFoundryAgentGateway",
            "ai_provider": "microsoft-foundry",
            "available_agents": [role.value for role in AgentRole],
            "fallback_enabled": settings.agents.fallback_enabled,
            "configured": True,
            "telemetry": None,
        }
    orchestrator = _orchestrator()
    return orchestrator.status() | {"telemetry": orchestrator.telemetry.model_dump(mode="json")}


@app.post("/api/agents/invoke")
def invoke_agent(payload: dict) -> dict:
    insight_id = UUID(str(payload["insight_id"]))
    result = _orchestrator().invoke_for_insight(insight_id)
    return result.model_dump(mode="json")


@app.get("/api/agents/invocations")
def agent_invocations() -> list[dict]:
    orchestrator = _orchestrator()
    return [
        invocation.model_dump(mode="json")
        for trace in orchestrator.traces.values()
        for invocation in trace.invocations
    ]


@app.get("/api/agents/invocations/{invocation_id}")
def agent_invocation(invocation_id: UUID) -> dict:
    orchestrator = _orchestrator()
    response = orchestrator.responses.get(invocation_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Invocation not found")
    return response.model_dump(mode="json")


@app.get("/api/insights/{insight_id}/agents")
def insight_agents(insight_id: UUID) -> dict:
    orchestrator = _orchestrator()
    trace = orchestrator.traces.get(insight_id)
    if trace is None:
        result = orchestrator.invoke_for_insight(insight_id)
        trace = result.trace
    return trace.model_dump(mode="json")


@app.get("/api/insights/{insight_id}/claims")
def insight_claims(insight_id: UUID) -> list[dict]:
    processor = _active_processor()
    insight = next(item for item in processor.insights if item.insight_id == insight_id)
    return [claim.model_dump(mode="json") for claim in processor.claims if claim.pattern_id == insight.pattern_id]


@app.get("/api/insights/{insight_id}/validation")
def insight_validation(insight_id: UUID) -> list[dict]:
    processor = _active_processor()
    insight = next(item for item in processor.insights if item.insight_id == insight_id)
    return [
        validation.model_dump(mode="json")
        for validation in processor.validations
        if validation.claim_id == insight.claim_id
    ]


@app.get("/api/insights/{insight_id}/trace")
def insight_trace(insight_id: UUID) -> dict:
    processor = _active_processor()
    processing = next(
        (trace for trace in processor.processing_traces if trace.insight_id == insight_id),
        None,
    )
    agent = _orchestrator().traces.get(insight_id)
    return {
        "processing_trace": processing.model_dump(mode="json") if processing else None,
        "agent_trace": agent.model_dump(mode="json") if agent else None,
    }


@app.get("/api/prompts")
def prompts() -> list[dict]:
    return [prompt.model_dump(mode="json") for prompt in PromptRegistry().list_prompts()]


@app.get("/api/prompts/{agent}/{version}")
def prompt(agent: str, version: str) -> dict:
    from domain.enums import AgentRole

    prompt_version = PromptRegistry().get(AgentRole(agent.upper()), version)
    if prompt_version is None:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return prompt_version.model_dump(mode="json")


def _processor(match_id: UUID) -> MatchProcessor:
    if not runtime.processor or runtime.processor.context.match_id != match_id:
        raise HTTPException(status_code=404, detail="Match not found")
    return runtime.processor


def _active_processor() -> MatchProcessor:
    if runtime.processor is None:
        raise HTTPException(status_code=404, detail="No active match")
    return runtime.processor


def _context_builder() -> AgentContextBuilder:
    if runtime.processor is None:
        raise HTTPException(status_code=404, detail="No active match")
    return AgentContextBuilder(runtime.processor)


def _orchestrator() -> AgentOrchestrator:
    if runtime.processor is None:
        raise HTTPException(status_code=404, detail="No active match")
    if runtime.orchestrator is None:
        runtime.orchestrator = AgentOrchestrator(runtime.processor, load_settings())
    assert runtime.orchestrator is not None
    return runtime.orchestrator
