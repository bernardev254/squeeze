"""Consume a finite Event Hubs run through SQUEEZE processing and agents.

Usage:
    python3 scripts/end_to_end_eventhub_smoke.py --expected-events 19 --agents

Start this consumer before publishing a scenario with ``make publish-scenario``.
The local repository and logging dead-letter sink make this a smoke test only;
production state and dead letters must use durable Azure implementations.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from typing import Any

from domain.events.envelope import EventEnvelope
from services.agents.orchestrator import AgentOrchestrator
from services.cloud.logging_dead_letter import LoggingDeadLetterSink
from services.cloud.processor import CloudEventProcessor
from services.repositories.local_match_state import LocalLoggingMatchStateRepository
from services.settings import Settings

logger = logging.getLogger("end_to_end_eventhub_smoke")


def _eventhub_client(
    connection: str | None,
    namespace: str | None,
    eventhub_name: str,
    consumer_group: str,
    use_ws: bool,
) -> Any:
    from azure.eventhub import TransportType
    from azure.eventhub.aio import EventHubConsumerClient

    transport = TransportType.AmqpOverWebsocket if use_ws else TransportType.Amqp
    if connection:
        kwargs: dict[str, Any] = {
            "conn_str": connection,
            "consumer_group": consumer_group,
            "transport_type": transport,
        }
        if "entitypath=" not in connection.lower():
            kwargs["eventhub_name"] = eventhub_name
        return EventHubConsumerClient.from_connection_string(**kwargs)
    if not namespace:
        raise RuntimeError(
            "Configure SQUEEZE_EVENT_HUB_CONNECTION_STRING or "
            "SQUEEZE_EVENT_HUB_NAMESPACE"
        )
    from azure.identity.aio import DefaultAzureCredential

    return EventHubConsumerClient(
        fully_qualified_namespace=namespace,
        eventhub_name=eventhub_name,
        consumer_group=consumer_group,
        credential=DefaultAzureCredential(),
        transport_type=transport,
    )


def _envelope_from_event(event: Any) -> EventEnvelope:
    body = event.body_as_str(encoding="UTF-8")
    return EventEnvelope.model_validate(json.loads(body))


async def run(expected_events: int, starting_position: str, invoke_agents: bool) -> dict[str, Any]:
    if expected_events < 1:
        raise ValueError("--expected-events must be greater than zero")

    settings = Settings()
    connection = settings.event_stream.connection_string
    namespace = settings.event_stream.event_hub_namespace
    if not connection and not namespace:
        raise RuntimeError(
            "Configure SQUEEZE_EVENT_HUB_CONNECTION_STRING or "
            "SQUEEZE_EVENT_HUB_NAMESPACE"
        )

    processor = CloudEventProcessor(
        repository=LocalLoggingMatchStateRepository(),
        dead_letters=LoggingDeadLetterSink(),
        settings=settings,
    )
    orchestrators: dict[str, AgentOrchestrator] = {}
    consumed = 0
    accepted_events = 0
    agent_invocations = 0
    agent_fallbacks = 0
    done = asyncio.Event()
    use_ws = os.getenv("SQUEEZE_EH_USE_WEBSOCKET", "false").lower() in {"1", "true", "yes"}
    client = _eventhub_client(
        connection,
        namespace,
        settings.event_stream.event_hub_name,
        settings.event_stream.consumer_group,
        use_ws,
    )

    async def on_event(partition_context: Any, event: Any) -> None:
        nonlocal consumed, accepted_events, agent_invocations, agent_fallbacks
        if done.is_set():
            return
        envelope = _envelope_from_event(event)
        result = processor.process_envelope(envelope)
        consumed += 1
        if result is not None:
            accepted_events += 1
        logger.info(
            "smoke_event_processed partition=%s sequence=%s accepted=%s event_type=%s",
            partition_context.partition_id,
            event.sequence_number,
            result is not None,
            envelope.event_type,
        )
        if result is not None and invoke_agents and result.insights_created:
            record = processor.repository.get(envelope.match_id)
            if record is None:
                raise RuntimeError(f"Processor state missing for match {envelope.match_id}")
            key = str(envelope.match_id)
            orchestrator = orchestrators.setdefault(key, AgentOrchestrator(record.processor, settings))
            for insight in result.insights_created:
                agent_result = orchestrator.invoke_for_insight(insight.insight_id)
                agent_invocations += len(agent_result.responses)
                agent_fallbacks += int(agent_result.fallback_used)
                logger.info(
                    "smoke_agents_completed insight=%s responses=%s fallback=%s",
                    insight.insight_id,
                    len(agent_result.responses),
                    agent_result.fallback_used,
                )
        await partition_context.update_checkpoint(event)
        if accepted_events >= expected_events:
            done.set()

    async def on_error(partition_context: Any, error: Exception) -> None:
        logger.error("eventhub_receive_error partition=%s error=%s", getattr(partition_context, "partition_id", None), error)

    receive_task = asyncio.create_task(
        client.receive(on_event=on_event, on_error=on_error, starting_position=starting_position)
    )
    try:
        await done.wait()
    finally:
        receive_task.cancel()
        await asyncio.gather(receive_task, return_exceptions=True)
        await client.close()

    return {
        "expected_events": expected_events,
        "consumed_events": consumed,
        "accepted_events": accepted_events,
        "processor": processor.status(),
        "agent_invocations": agent_invocations,
        "agent_fallbacks": agent_fallbacks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-events", type=int, required=True)
    parser.add_argument("--starting-position", default="@latest")
    parser.add_argument("--agents", action="store_true", help="invoke configured Microsoft Foundry agents")
    args = parser.parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    logging.getLogger("azure.eventhub").setLevel(logging.WARNING)
    print(json.dumps(asyncio.run(run(args.expected_events, args.starting_position, args.agents)), indent=2, default=str))


if __name__ == "__main__":
    main()
