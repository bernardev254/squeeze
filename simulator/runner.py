from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid5

from domain.events.envelope import EventEnvelope
from simulator.scenarios import SIMULATION_NAMESPACE, SIMULATOR_VERSION, ScenarioBundle
from simulator.sinks import EventSink

logger = logging.getLogger(__name__)


@dataclass
class SimulationRunMetadata:
    run_id: str
    scenario: str
    seed: int
    match_id: str
    home_team: str
    away_team: str
    start_time: datetime
    event_count: int
    simulator_version: str
    schema_version: str


@dataclass
class SimulatorMetrics:
    events_generated: int = 0
    events_published: int = 0
    publish_failures: int = 0
    batches_sent: int = 0
    publish_latency_ms: float = 0.0


def metadata_for_bundle(bundle: ScenarioBundle) -> SimulationRunMetadata:
    return SimulationRunMetadata(
        run_id=str(uuid5(SIMULATION_NAMESPACE, f"{bundle.scenario}:{bundle.seed}:run")),
        scenario=bundle.scenario,
        seed=bundle.seed,
        match_id=str(bundle.context.match_id),
        home_team=bundle.context.home_team.name,
        away_team=bundle.context.away_team.name,
        start_time=datetime.now(UTC),
        event_count=len(bundle.events),
        simulator_version=SIMULATOR_VERSION,
        schema_version="1.0",
    )


class MatchSimulator:
    def __init__(
        self,
        bundle: ScenarioBundle,
        sink: EventSink,
        speed: float = 0,
        min_delay_ms: int = 500,
        max_delay_ms: int = 4000,
    ) -> None:
        self.bundle = bundle
        self.sink = sink
        self.speed = speed
        self.min_delay_s = max(0.0, min_delay_ms / 1000)
        self.max_delay_s = max(0.0, max_delay_ms / 1000)
        self.metrics = SimulatorMetrics(events_generated=len(bundle.events))

    def run(self) -> list[EventEnvelope]:
        envelopes: list[EventEnvelope] = []
        previous_second: int | None = None
        try:
            for event in self.bundle.events:
                self._sleep_for_playback(previous_second, event.match_clock.total_seconds())
                previous_second = event.match_clock.total_seconds()
                envelope = EventEnvelope.from_event(
                    event,
                    scenario=self.bundle.scenario,
                    seed=self.bundle.seed,
                )
                started = time.perf_counter()
                self.sink.publish(envelope)
                self.metrics.publish_latency_ms += (time.perf_counter() - started) * 1000
                self.metrics.events_published += 1
                envelopes.append(envelope)
                logger.info(
                    "event_published",
                    extra={
                        "event_id": str(envelope.event_id),
                        "match_id": str(envelope.match_id),
                        "sequence": envelope.sequence,
                        "event_type": envelope.event_type,
                        "scenario": envelope.scenario,
                        "seed": envelope.seed,
                    },
                )
                print(
                    f"{event.match_clock.display():>5}  "
                    f"{envelope.event_type:<14} seq={envelope.sequence:<3} "
                    f"event={str(envelope.event_id)[:8]}"
                )
            return envelopes
        except KeyboardInterrupt:
            logger.warning("simulation_interrupted")
            raise
        except Exception:
            self.metrics.publish_failures += 1
            logger.exception(
                "simulation_failed",
                extra={"scenario": self.bundle.scenario, "seed": self.bundle.seed},
            )
            raise
        finally:
            self.sink.close()

    def _sleep_for_playback(self, previous_second: int | None, current_second: int) -> None:
        if previous_second is None or self.speed <= 0:
            return
        raw_delay = max(0, current_second - previous_second) / self.speed
        delay = min(raw_delay, self.max_delay_s) if self.max_delay_s else raw_delay
        delay = max(delay, self.min_delay_s)
        if delay:
            time.sleep(delay)
