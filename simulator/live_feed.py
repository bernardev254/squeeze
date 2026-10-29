from __future__ import annotations

import argparse
import time

from services.settings import load_settings
from services.streaming.azure_event_hubs import AzureEventHubEventStream
from simulator.runner import MatchSimulator
from simulator.scenarios import generate_scenario
from simulator.sinks import AzureEventHubSink


def main() -> None:
    settings = load_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default=settings.live_feed.scenario)
    parser.add_argument("--seed", type=int, default=settings.live_feed.seed)
    parser.add_argument("--speed", type=float, default=settings.live_feed.speed)
    parser.add_argument("--min-delay-ms", type=int, default=settings.live_feed.min_delay_ms)
    parser.add_argument("--max-delay-ms", type=int, default=settings.live_feed.max_delay_ms)
    parser.add_argument("--loop", action="store_true", default=settings.live_feed.loop)
    args = parser.parse_args()

    loop_count = 0
    while True:
        bundle = generate_scenario(args.scenario, args.seed + loop_count)
        sink = AzureEventHubSink(
            AzureEventHubEventStream(
                settings.event_stream.connection_string,
                settings.event_stream.event_hub_name,
                event_hub_namespace=settings.event_stream.event_hub_namespace,
                batch_size=settings.event_stream.batch_size,
                retry_total=settings.event_stream.retry_total,
            )
        )
        simulator = MatchSimulator(
            bundle,
            sink=sink,
            speed=args.speed,
            min_delay_ms=args.min_delay_ms,
            max_delay_ms=args.max_delay_ms,
        )
        simulator.run()
        print(
            {
                "events_generated": simulator.metrics.events_generated,
                "events_published": simulator.metrics.events_published,
                "publish_failures": simulator.metrics.publish_failures,
                "scenario": args.scenario,
                "seed": args.seed + loop_count,
                "match_id": str(bundle.context.match_id),
                "playback_speed": args.speed,
            }
        )
        if not args.loop:
            break
        loop_count += 1
        time.sleep(5)


if __name__ == "__main__":
    main()
