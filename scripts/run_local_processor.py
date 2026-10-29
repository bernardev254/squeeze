"""Run a local CloudEventProcessor wired with logging sinks for smoke tests.

Usage: set your Event Hubs env vars and run:

    python3 scripts/run_local_processor.py

It will subscribe to the configured event hub and pass envelopes to
`CloudEventProcessor` using in-process logging repository and dead-letter sink.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from azure.eventhub import TransportType
from azure.eventhub.aio import EventHubConsumerClient

from services.cloud.processor import CloudEventProcessor
from services.cloud.logging_dead_letter import LoggingDeadLetterSink
from services.repositories.local_match_state import LocalLoggingMatchStateRepository
from domain.events.envelope import EventEnvelope

logger = logging.getLogger("local_processor")
logging.basicConfig(level=logging.INFO)


def envelope_from_event(event: Any) -> EventEnvelope:
    body = event.body_as_str(encoding="UTF-8")
    payload = json.loads(body)
    return EventEnvelope.model_validate(payload)


async def on_event(partition_context, event):
    logger.info("RECEIVED partition=%s sequence=%s offset=%s", partition_context.partition_id, event.sequence_number, event.offset)
    envelope = envelope_from_event(event)
    result = processor.process_envelope(envelope)
    logger.info("processed_result: %s", result)
    await partition_context.update_checkpoint(event)


async def main():
    # prefer explicit event hub name if provided
    connection = os.environ.get("SQUEEZE_EVENT_HUB_CONNECTION_STRING")
    eventhub_name = os.environ.get("SQUEEZE_EVENT_HUB_NAME")
    consumer_group = os.environ.get("SQUEEZE_EVENT_HUB_CONSUMER_GROUP", "$Default")
    use_ws = os.environ.get("SQUEEZE_EH_USE_WEBSOCKET", "false").lower() in ("1", "true", "yes")

    if not connection:
        raise RuntimeError("SQUEEZE_EVENT_HUB_CONNECTION_STRING is required")

    transport = TransportType.AmqpOverWebsocket if use_ws else TransportType.Amqp

    # If the connection string already includes EntityPath, prefer it and
    # ignore an explicit `SQUEEZE_EVENT_HUB_NAME` to avoid double-specifying
    # the target event hub which can lead to link attach failures.
    if "entitypath=" in connection.lower():
        if eventhub_name:
            logger.info("Connection string contains EntityPath; ignoring SQUEEZE_EVENT_HUB_NAME=%s", eventhub_name)
        eventhub_name = None

    if eventhub_name:
        client = EventHubConsumerClient.from_connection_string(
            conn_str=connection,
            consumer_group=consumer_group,
            eventhub_name=eventhub_name,
            transport_type=transport,
        )
    else:
        client = EventHubConsumerClient.from_connection_string(
            conn_str=connection, consumer_group=consumer_group, transport_type=transport
        )

    global processor
    processor = CloudEventProcessor(repository=LocalLoggingMatchStateRepository(), dead_letters=LoggingDeadLetterSink())

    async with client:
        await client.receive(on_event=on_event)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
