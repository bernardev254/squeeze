from __future__ import annotations

import json
import logging
from threading import Event, Lock, Thread
from typing import Any, Protocol

from domain.events.envelope import EventEnvelope
from services.cloud.logging_dead_letter import LoggingDeadLetterSink
from services.cloud.processor import CloudEventProcessor, ProcessingResult
from services.repositories.local_match_state import LocalLoggingMatchStateRepository
from services.settings import Settings

logger = logging.getLogger(__name__)


class RuntimeUpdateCallback(Protocol):
    def __call__(self, result: ProcessingResult, processor: object) -> None: ...


class LiveRuntimeBridge:
    """Consumes a dedicated Event Hubs view and mirrors it into API runtime state."""

    def __init__(self, settings: Settings, on_update: RuntimeUpdateCallback) -> None:
        self.settings = settings
        self.on_update = on_update
        self.repository = LocalLoggingMatchStateRepository()
        self.processor = CloudEventProcessor(
            repository=self.repository,
            dead_letters=LoggingDeadLetterSink(),
            settings=settings,
        )
        self._stop_event = Event()
        self._lock = Lock()
        self._thread: Thread | None = None
        self._client: object | None = None
        self._error: str | None = None
        self._connected = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = Thread(target=self._run, name="squeeze-live-runtime", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        client = self._client
        if client is not None:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "enabled": True,
                "connected": self._connected,
                "consumer_group": self.settings.dashboard_stream.consumer_group,
                "starting_position": self.settings.dashboard_stream.starting_position,
                "error": self._error,
                "events_processed": self.processor.events_processed_total,
                "events_failed": self.processor.events_failed_total,
            }

    def _run(self) -> None:
        try:
            from azure.eventhub import EventHubConsumerClient

            event_stream = self.settings.event_stream
            if event_stream.connection_string:
                event_hub_name = (
                    None
                    if "entitypath=" in event_stream.connection_string.lower()
                    else event_stream.event_hub_name
                )
                client = EventHubConsumerClient.from_connection_string(
                    conn_str=event_stream.connection_string,
                    consumer_group=self.settings.dashboard_stream.consumer_group,
                    eventhub_name=event_hub_name,
                )
            elif event_stream.event_hub_namespace:
                from azure.identity import DefaultAzureCredential

                client = EventHubConsumerClient(
                    fully_qualified_namespace=event_stream.event_hub_namespace,
                    eventhub_name=event_stream.event_hub_name,
                    consumer_group=self.settings.dashboard_stream.consumer_group,
                    credential=DefaultAzureCredential(),
                )
            else:
                raise RuntimeError("Azure Event Hubs configuration is required for the live dashboard")
            self._client = client
            with client:
                with self._lock:
                    self._connected = True
                    self._error = None
                client.receive(
                    on_event=self._on_event,
                    starting_position=self.settings.dashboard_stream.starting_position,
                )
        except Exception as exc:
            if not self._stop_event.is_set():
                logger.exception("live_runtime_bridge_stopped")
                with self._lock:
                    self._error = str(exc)
        finally:
            with self._lock:
                self._connected = False
            self._client = None

    def _on_event(self, partition_context: Any, event: Any) -> None:
        body = event.body
        payload = b"".join(body) if not isinstance(body, (str, bytes)) else body
        payload_text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        envelope = EventEnvelope.from_dict(json.loads(payload_text))
        result = self.processor.process_envelope(envelope)
        if result is None:
            return
        record = self.repository.get(envelope.match_id)
        if record is None:
            return
        self.on_update(result, record.processor)
        checkpoint = getattr(partition_context, "update_checkpoint", None)
        if callable(checkpoint):
            checkpoint(event)
