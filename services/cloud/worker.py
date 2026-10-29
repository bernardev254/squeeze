from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from domain.events.envelope import EventEnvelope
from services.cloud.logging_dead_letter import LoggingDeadLetterSink
from services.cloud.processor import CloudEventProcessor
from services.repositories.local_match_state import LocalLoggingMatchStateRepository
from services.settings import load_settings

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--starting-position", default="-1")
    args = parser.parse_args()

    settings = load_settings()
    processor = CloudEventProcessor(
        repository=LocalLoggingMatchStateRepository(),
        dead_letters=LoggingDeadLetterSink(),
        settings=settings,
    )
    print("-" * 60)
    print("SQUEEZE INGESTION")
    print("-" * 60)
    print(f"Event Hub: {settings.event_stream.event_hub_name}")
    print(f"Consumer group: {settings.event_stream.consumer_group}")
    print()
    _consume_event_hub(processor, args.starting_position)


def _consume_event_hub(processor: CloudEventProcessor, starting_position: str) -> None:
    settings = processor.settings
    try:
        from azure.eventhub import EventHubConsumerClient
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:
        raise RuntimeError("azure-eventhub and azure-identity are required for ingestion") from exc

    def on_event(partition_context: Any, event: Any) -> None:
        body = b"".join(event.body) if not isinstance(event.body, (str, bytes)) else event.body
        if isinstance(body, bytes):
            body_text = body.decode("utf-8")
        else:
            body_text = body
        envelope = EventEnvelope.from_dict(json.loads(body_text))
        result = processor.process_envelope(envelope)
        if result is not None:
            partition_context.update_checkpoint(event)
        logger.info(
            "eventhub_event_consumed",
            extra={
                "partition_id": getattr(partition_context, "partition_id", None),
                "offset": getattr(event, "offset", None),
                "sequence_number": getattr(event, "sequence_number", None),
                "enqueued_time": str(getattr(event, "enqueued_time", "")),
                "accepted": result is not None,
            },
        )

    if settings.event_stream.connection_string:
        client = EventHubConsumerClient.from_connection_string(
            conn_str=settings.event_stream.connection_string,
            consumer_group=settings.event_stream.consumer_group,
            eventhub_name=settings.event_stream.event_hub_name,
        )
    else:
        if not settings.event_stream.event_hub_namespace:
            raise RuntimeError("Event Hubs namespace is required for passwordless ingestion")
        client = EventHubConsumerClient(
            fully_qualified_namespace=settings.event_stream.event_hub_namespace,
            eventhub_name=settings.event_stream.event_hub_name,
            consumer_group=settings.event_stream.consumer_group,
            credential=DefaultAzureCredential(),
        )
    with client:
        client.receive(on_event=on_event, starting_position=starting_position)


if __name__ == "__main__":
    main()
