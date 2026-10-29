from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from domain.common import DomainModel, utc_now
from domain.events.base import MatchEvent

SUPPORTED_EVENT_ENVELOPE_SCHEMAS = {"1.0"}


class EventEnvelope(DomainModel):
    schema_version: str = "1.0"
    event_id: UUID
    match_id: UUID
    sequence: int
    event_time: datetime
    event_type: str
    source: str = "squeeze-simulator"
    producer: str = "squeeze-simulator"
    scenario: str | None = None
    seed: int | None = None
    correlation_id: str | None = None
    payload: dict
    timestamp: datetime | None = Field(
        default=None,
        description="Backward-compatible alias for event_time.",
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_timestamp(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "event_time" not in data and "timestamp" in data:
                data = data | {"event_time": data["timestamp"]}
            if data.get("correlation_id") is None and data.get("match_id") is not None:
                data = data | {"correlation_id": str(data["match_id"])}
        return data

    @model_validator(mode="after")
    def _mirror_timestamp(self) -> EventEnvelope:
        if self.timestamp is None:
            self.timestamp = self.event_time
        if self.correlation_id is None:
            self.correlation_id = str(self.match_id)
        return self

    @classmethod
    def from_event(
        cls,
        event: MatchEvent,
        producer: str = "squeeze-simulator",
        correlation_id: str | None = None,
        scenario: str | None = None,
        seed: int | None = None,
    ) -> EventEnvelope:
        return cls(
            event_id=event.event_id,
            match_id=event.match_id,
            sequence=event.sequence,
            event_type=event.event_type.value,
            event_time=event.timestamp,
            timestamp=event.timestamp,
            schema_version=event.schema_version,
            source=event.source,
            producer=producer,
            scenario=scenario,
            seed=seed,
            correlation_id=correlation_id or str(event.match_id),
            payload=event.model_dump(mode="json"),
        )

    @classmethod
    def from_dict(cls, data: dict) -> EventEnvelope:
        return cls.model_validate(data)

    def to_dict(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)

    @classmethod
    def dead_letter_probe(cls, payload: dict) -> EventEnvelope:
        return cls(
            event_id=uuid4(),
            match_id=uuid4(),
            sequence=-1,
            event_type="INVALID",
            event_time=utc_now(),
            correlation_id="dead-letter-probe",
            payload=payload,
        )


def validate_envelope_schema(envelope: EventEnvelope) -> None:
    if envelope.schema_version not in SUPPORTED_EVENT_ENVELOPE_SCHEMAS:
        raise ValueError(f"Unsupported event envelope schema {envelope.schema_version}")
    if not envelope.event_id:
        raise ValueError("Envelope missing event_id")
    if not envelope.match_id:
        raise ValueError("Envelope missing match_id")
    if envelope.sequence < 0:
        raise ValueError("Envelope sequence must be non-negative")
    payload = envelope.payload
    for field in ("event_id", "match_id", "sequence", "match_clock", "period", "event_type"):
        if field not in payload:
            raise ValueError(f"Envelope payload missing {field}")
    if str(payload["event_id"]) != str(envelope.event_id):
        raise ValueError("Envelope event_id does not match payload")
    if str(payload["match_id"]) != str(envelope.match_id):
        raise ValueError("Envelope match_id does not match payload")
    if int(payload["sequence"]) != envelope.sequence:
        raise ValueError("Envelope sequence does not match payload")
