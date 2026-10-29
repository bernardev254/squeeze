from __future__ import annotations

from services.cloud.processor import CloudEventProcessor
from services.repositories.local_match_state import LocalLoggingMatchStateRepository
from services.settings import AppSettings, Settings
from simulator.scenarios import generate_scenario
from domain.events.envelope import EventEnvelope


class RecordingDeadLetterSink:
    def __init__(self) -> None:
        self.records: list[object] = []

    def record(self, record: object) -> None:
        self.records.append(record)


def _make_processor(app_env: str) -> tuple[CloudEventProcessor, RecordingDeadLetterSink]:
    sink = RecordingDeadLetterSink()
    processor = CloudEventProcessor(
        repository=LocalLoggingMatchStateRepository(),
        dead_letters=sink,
        settings=Settings(app=AppSettings(app_env=app_env)),
    )
    return processor, sink


def test_duplicate_events_are_ignored_in_development_mode() -> None:
    bundle = generate_scenario("press_counter_goal", seed=42)
    envelope = EventEnvelope.from_event(bundle.events[0], scenario=bundle.scenario, seed=bundle.seed)

    processor, sink = _make_processor("development")

    first = processor.process_envelope(envelope)
    second = processor.process_envelope(envelope)

    assert first is not None
    assert second is None
    assert sink.records == []


def test_duplicate_events_still_dead_letter_in_production() -> None:
    bundle = generate_scenario("press_counter_goal", seed=42)
    envelope = EventEnvelope.from_event(bundle.events[0], scenario=bundle.scenario, seed=bundle.seed)

    processor, sink = _make_processor("production")

    processor.process_envelope(envelope)
    processor.process_envelope(envelope)

    assert len(sink.records) == 1
