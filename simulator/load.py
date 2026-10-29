from __future__ import annotations

import argparse
import itertools
import time
from uuid import uuid5

from domain.common import MatchClock
from domain.enums import Period
from domain.events.envelope import EventEnvelope
from services.settings import load_settings
from services.streaming.azure_event_hubs import AzureEventHubEventStream
from simulator.scenarios import SIMULATION_NAMESPACE, generate_scenario
from simulator.sinks import AzureEventHubSink


def _clock_from_seconds(total_seconds: int) -> MatchClock:
    minute, second = divmod(total_seconds, 60)
    period = Period.SECOND_HALF if minute >= 45 else Period.FIRST_HALF
    return MatchClock(period=period, minute=minute, second=second)


def main() -> None:
    settings = load_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-count", type=int, default=10)
    parser.add_argument("--events-per-match", type=int, default=1000)
    parser.add_argument("--rate", type=float, default=500)
    args = parser.parse_args()

    sink = AzureEventHubSink(
        AzureEventHubEventStream(
            settings.event_stream.connection_string,
            settings.event_stream.event_hub_name,
            event_hub_namespace=settings.event_stream.event_hub_namespace,
            batch_size=settings.event_stream.batch_size,
            retry_total=settings.event_stream.retry_total,
        )
    )
    interval = 1 / args.rate if args.rate > 0 else 0
    published = 0
    started = time.perf_counter()
    try:
        for match_index in range(args.match_count):
            bundle = generate_scenario("press_counter_goal", seed=42 + match_index)
            for sequence, event in enumerate(
                itertools.islice(itertools.cycle(bundle.events), args.events_per_match),
                start=1,
            ):
                repeat = (sequence - 1) // len(bundle.events)
                synthetic = event.model_copy(
                    update={
                        "sequence": sequence,
                        "event_id": uuid5(
                            SIMULATION_NAMESPACE,
                            f"load:{match_index}:{bundle.context.match_id}:{sequence}",
                        ),
                        "match_clock": _clock_from_seconds(
                            event.match_clock.total_seconds() + repeat * 120
                        ),
                    }
                )
                envelope = EventEnvelope.from_event(
                    synthetic,
                    scenario=f"load_press_counter_goal_{match_index}",
                    seed=42 + match_index,
                )
                sink.publish(envelope)
                published += 1
                if interval:
                    time.sleep(interval)
    finally:
        sink.close()
    elapsed = time.perf_counter() - started
    print(
        {
            "target": "azure-event-hubs",
            "events_published": published,
            "elapsed_seconds": round(elapsed, 3),
            "rate_per_second": round(published / elapsed, 2) if elapsed else published,
        }
    )


if __name__ == "__main__":
    main()
