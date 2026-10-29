from __future__ import annotations

from domain.events.envelope import EventEnvelope
from services.streaming.event_hub_producer import AzureEventHubProducer


class AzureEventHubEventStream:
    """Publisher boundary for Azure Event Hubs transport envelopes."""

    def __init__(
        self,
        connection_string: str | None,
        event_hub_name: str,
        producer: str = "squeeze-simulator",
        eventhub_producer: AzureEventHubProducer | None = None,
        event_hub_namespace: str | None = None,
        batch_size: int = 100,
        retry_total: int = 3,
    ) -> None:
        self.connection_string = connection_string
        self.event_hub_name = event_hub_name
        self.producer = producer
        self._producer = eventhub_producer
        self.event_hub_namespace = event_hub_namespace
        self.batch_size = batch_size
        self.retry_total = retry_total

    def publish_envelope(self, envelope: EventEnvelope) -> None:
        if not (self.connection_string or self.event_hub_namespace):
            raise RuntimeError("Azure Event Hubs publishing requires a namespace or connection string")
        self._publish_to_azure(envelope)

    def deserialize(self, body: str | bytes) -> EventEnvelope:
        import json

        data = json.loads(body.decode() if isinstance(body, bytes) else body)
        return EventEnvelope.from_dict(data)

    def serialize(self, envelope: EventEnvelope) -> str:
        import json

        return json.dumps(envelope.to_dict(), separators=(",", ":"))

    def _publish_to_azure(self, envelope: EventEnvelope) -> None:
        if self._producer is None:
            self._producer = AzureEventHubProducer(
                connection_string=self.connection_string,
                event_hub_name=self.event_hub_name,
                fully_qualified_namespace=self.event_hub_namespace,
                batch_size=self.batch_size,
                retry_total=self.retry_total,
            )
        producer = self._producer
        producer.publish([envelope])

    def close(self) -> None:
        if self._producer is not None:
            self._producer.close()
