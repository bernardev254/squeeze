"""Event Hubs consumer that forwards envelopes to CloudEventProcessor for local testing.

Run with:
  PYTHONPATH=. python3 scripts/eh_processor_consumer.py
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eh_processor_consumer")


def envelope_from_event(event: Any) -> EventEnvelope:
    body = event.body_as_str(encoding="UTF-8")
    payload = json.loads(body)
    return EventEnvelope.model_validate(payload)


async def on_event(partition_context, event):
    logger.info("RECEIVED partition=%s sequence=%s offset=%s", partition_context.partition_id, event.sequence_number, event.offset)
    envelope = envelope_from_event(event)
    result = processor.process_envelope(envelope)
    logger.info("processed_result=%s", result)
    await partition_context.update_checkpoint(event)


async def main():
    connection = os.environ.get("SQUEEZE_EVENT_HUB_CONNECTION_STRING")
    eventhub_name = os.environ.get("SQUEEZE_EVENT_HUB_NAME")
    consumer_group = os.environ.get("SQUEEZE_EVENT_HUB_CONSUMER_GROUP", "$Default")
    use_ws = os.environ.get("SQUEEZE_EH_USE_WEBSOCKET", "false").lower() in ("1", "true", "yes")
    if not connection:
        raise RuntimeError("SQUEEZE_EVENT_HUB_CONNECTION_STRING is required")

    transport = TransportType.AmqpOverWebsocket if use_ws else TransportType.Amqp

    # If EntityPath present in connection string, prefer it and ignore
    # the environment `SQUEEZE_EVENT_HUB_NAME` to avoid conflicting targets.
    # Mirror the verbose consumer's lifecycle and callbacks for stability.
    client = EventHubConsumerClient.from_connection_string(
        conn_str=connection, consumer_group=consumer_group, eventhub_name=eventhub_name or None, transport_type=transport
    )

    async def on_error(partition_context, error):
        if partition_context:
            logger.error("Error on partition %s: %s", partition_context.partition_id, error)
        else:
            logger.error("Client error: %s", error)

    async def on_partition_initialize(partition_context):
        logger.info("Initialized partition: %s", partition_context.partition_id)

    async def on_partition_close(partition_context, reason):
        logger.info("Closed partition: %s reason=%s", partition_context.partition_id, reason)

    global processor
    processor = CloudEventProcessor(repository=LocalLoggingMatchStateRepository(), dead_letters=LoggingDeadLetterSink())

    try:
        receive_task = asyncio.create_task(
            client.receive(
                on_event=on_event,
                on_error=on_error,
                on_partition_initialize=on_partition_initialize,
                on_partition_close=on_partition_close,
                starting_position="-1",
            )
        )
        await receive_task
    except asyncio.CancelledError:
        logger.info("Receive task cancelled")
    finally:
        await client.close()
        logger.info("Client closed")


if __name__ == "__main__":
    asyncio.run(main())
