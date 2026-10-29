from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from importlib.util import find_spec
from typing import Any

from domain.events.envelope import EventEnvelope

logger = logging.getLogger(__name__)


def _azure_eventhub_available() -> bool:
    try:
        return find_spec("azure.eventhub") is not None
    except ModuleNotFoundError:
        return False


@dataclass
class EventHubPublishMetrics:
    events_published: int = 0
    publish_failures: int = 0
    batches_sent: int = 0
    publish_latency_ms: float = 0.0


class AzureEventHubProducer:
    """Batching Event Hubs producer for SQUEEZE transport envelopes."""

    def __init__(
        self,
        *,
        connection_string: str | None,
        event_hub_name: str,
        fully_qualified_namespace: str | None = None,
        credential: Any | None = None,
        batch_size: int = 100,
        retry_total: int = 3,
        client: Any | None = None,
    ) -> None:
        self.connection_string = connection_string
        self.event_hub_name = event_hub_name
        self.fully_qualified_namespace = fully_qualified_namespace
        self.credential = credential
        self.batch_size = batch_size
        self.retry_total = retry_total
        self._client = client
        self._owns_client = client is None
        self.metrics = EventHubPublishMetrics()

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def publish(self, envelopes: list[EventEnvelope]) -> None:
        if not envelopes:
            return
        started = time.perf_counter()
        try:
            for partition_key, group in self._group_by_match(envelopes).items():
                self._publish_partition(partition_key, group)
            self.metrics.events_published += len(envelopes)
            self.metrics.publish_latency_ms += (time.perf_counter() - started) * 1000
        except Exception:
            self.metrics.publish_failures += len(envelopes)
            logger.exception("eventhub_publish_failed", extra={"event_count": len(envelopes)})
            raise

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            close()

    def _publish_partition(self, partition_key: str, envelopes: list[EventEnvelope]) -> None:
        current_batch = self.client.create_batch(partition_key=partition_key)
        current_size = 0
        for envelope in envelopes:
            event_data = self._event_data(envelope)
            try:
                current_batch.add(event_data)
                current_size += 1
            except ValueError as exc:
                if current_size == 0:
                    raise RuntimeError(
                        f"Event {envelope.event_id} exceeds Event Hubs maximum batch size"
                    ) from exc
                self.client.send_batch(current_batch)
                self.metrics.batches_sent += 1
                current_batch = self.client.create_batch(partition_key=partition_key)
                try:
                    current_batch.add(event_data)
                except ValueError as retry_exc:
                    raise RuntimeError(
                        f"Event {envelope.event_id} exceeds Event Hubs maximum batch size"
                    ) from retry_exc
                current_size = 1
            if current_size >= self.batch_size:
                self.client.send_batch(current_batch)
                self.metrics.batches_sent += 1
                current_batch = self.client.create_batch(partition_key=partition_key)
                current_size = 0
        if current_size:
            self.client.send_batch(current_batch)
            self.metrics.batches_sent += 1

    def _event_data(self, envelope: EventEnvelope) -> Any:
        body = json.dumps(envelope.to_dict(), separators=(",", ":"))
        if self._client is not None and not _azure_eventhub_available():
            return body
        from azure.eventhub import EventData

        event_data = EventData(body)
        event_data.properties = {
            "schema_version": envelope.schema_version,
            "event_type": envelope.event_type,
            "source": envelope.source,
            "match_id": str(envelope.match_id),
            "scenario": envelope.scenario or "",
        }
        return event_data

    def _build_client(self) -> Any:
        if not _azure_eventhub_available():
            raise RuntimeError("azure-eventhub is required for Event Hubs mode")
        from azure.eventhub import EventHubProducerClient

        if self.connection_string:
            return EventHubProducerClient.from_connection_string(
                conn_str=self.connection_string,
                eventhub_name=self._event_hub_name_for_connection_string(),
                retry_total=self.retry_total,
            )
        if not self.fully_qualified_namespace:
            raise RuntimeError(
                "Event Hubs mode requires a connection string or namespace plus credential"
            )
        credential = self.credential or self._default_credential()
        return EventHubProducerClient(
            fully_qualified_namespace=self.fully_qualified_namespace,
            eventhub_name=self.event_hub_name,
            credential=credential,
            retry_total=self.retry_total,
        )

    def _event_hub_name_for_connection_string(self) -> str | None:
        if "entitypath=" in (self.connection_string or "").lower():
            return None
        return self.event_hub_name

    def _default_credential(self) -> Any:
        try:
            from azure.identity import DefaultAzureCredential
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "azure-identity is required for passwordless Event Hubs authentication"
            ) from exc
        return DefaultAzureCredential()

    def _group_by_match(self, envelopes: list[EventEnvelope]) -> dict[str, list[EventEnvelope]]:
        grouped: dict[str, list[EventEnvelope]] = {}
        for envelope in envelopes:
            grouped.setdefault(str(envelope.match_id), []).append(envelope)
        return grouped
