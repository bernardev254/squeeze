from __future__ import annotations

from typing import Protocol

from domain.events.envelope import EventEnvelope
from services.streaming.azure_event_hubs import AzureEventHubEventStream


class EventSink(Protocol):
    def publish(self, envelope: EventEnvelope) -> None:
        ...

    def close(self) -> None:
        ...


class AzureEventHubSink:
    def __init__(self, stream: AzureEventHubEventStream) -> None:
        self.stream = stream

    def publish(self, envelope: EventEnvelope) -> None:
        self.stream.publish_envelope(envelope)

    def close(self) -> None:
        self.stream.close()

