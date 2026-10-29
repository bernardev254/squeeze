# SQUEEZE

SQUEEZE is the intelligence layer for football:

```text
EVENTS -> INTELLIGENCE -> STORY -> JUICE
```

The production runtime has one path:

```text
Azure Event Hubs
  -> ingestion worker
  -> canonical MatchEvent
  -> SQUEEZE Core deterministic intelligence
  -> InsightCandidate
  -> Microsoft Foundry
  -> deterministic validation
  -> narrative
  -> API / product
```

## Quick Start

Configure cloud dependencies first:

```bash
cp .env.example .env
make install
make test
make run
```

Missing Event Hubs or Foundry configuration fails clearly when application settings load. Tests may still construct canonical domain fixtures directly; that is not a runtime mode.

## Commands

```bash
make test
make lint
make typecheck
make eval
make publish-scenario SCENARIO=press_counter_goal SEED=42
make consume-eventhub
make eventhub-smoke EXPECTED_EVENTS=19 AGENTS=1
make load-test
make cloud-smoke-test
```

`make publish-scenario` and `make load-test` publish canonical envelopes into Azure Event Hubs. They do not bypass ingestion or call `MatchProcessor` directly.

The Make targets automatically load a root `.env` file when present. Copy `.env.example` to `.env` and fill in the Event Hubs connection string or namespace before running them.

For a bounded end-to-end check, start `make eventhub-smoke EXPECTED_EVENTS=19 AGENTS=1` in one terminal, then publish a fresh scenario in another, preferably with a new seed. The smoke runner starts at `@latest`, ignores duplicate historical events, consumes the requested number of accepted events, processes them through the cloud ingestion boundary, and invokes configured Foundry agents for generated insights. Without `AGENTS=1`, it validates Event Hubs through deterministic processing only. Direct invocation should use `PYTHONPATH=. python3 scripts/end_to_end_eventhub_smoke.py --expected-events 19`.

## Runtime Boundaries

- Event source: Azure Event Hubs.
- Football domain: canonical `MatchEvent` payloads and deterministic processing.
- AI provider: Microsoft Foundry only.
 - Fallback policy: provider failure is observable and uses deterministic SQUEEZE representations; external AI providers must be configured explicitly.
- Transport metadata stays separate from football facts.

## API

The API exposes production intelligence surfaces such as matches, events, metrics, action impacts, patterns, candidates, insights, evidence, agent status, and observability.

Safe status endpoints:

- `GET /health`
- `GET /ready`
- `GET /api/system/status`
- `GET /api/system/config`

`/ready` distinguishes application health from Event Hubs and Foundry configuration. `/api/system/config` omits secrets, tokens, connection strings, and credentials.
