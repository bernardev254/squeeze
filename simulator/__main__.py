from __future__ import annotations

import argparse

from services.settings import load_settings
from services.streaming.azure_event_hubs import AzureEventHubEventStream
from simulator.runner import MatchSimulator, metadata_for_bundle
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
    bundle = generate_scenario(args.scenario, seed=args.seed)
    metadata = metadata_for_bundle(bundle)
    print("-" * 60)
    print("SQUEEZE EVENT PRODUCER")
    print("-" * 60)
    print(f"Match: {metadata.match_id}")
    print(f"Scenario: {metadata.scenario}")
    print(f"Seed: {metadata.seed}")
    print("Target: Azure Event Hubs")
    print(f"Speed: {args.speed}x" if args.speed else "Speed: immediate")
    print()

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
    print()
    print(f"Published: {simulator.metrics.events_published}")
    print(f"Failed: {simulator.metrics.publish_failures}")
    print("-" * 60)


if __name__ == "__main__":
    main()
