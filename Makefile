.PHONY: install test lint typecheck run eval publish-scenario consume-eventhub eventhub-smoke infra-validate cloud-smoke-test load-test chaos-demo

install:
	python3 -m pip install -e ".[dev]"

test:
	python3 -m pytest

lint:
	python3 -m ruff check .

typecheck:
	python3 -m mypy domain simulator services

run:
	set -a; [ ! -f .env ] || . ./.env; set +a; python3 -m uvicorn services.match_engine.api:app --reload --host 127.0.0.1 --port 8000

eval:
	python3 -m evals

publish-scenario:
	set -a; [ ! -f .env ] || . ./.env; set +a; python3 -m simulator --scenario $${SCENARIO:-press_counter_goal} --seed $${SEED:-42} --speed $${SPEED:-0}

consume-eventhub:
	set -a; [ ! -f .env ] || . ./.env; set +a; python3 -m services.cloud.worker

eventhub-smoke:
	set -a; [ ! -f .env ] || . ./.env; set +a; PYTHONPATH=. python3 scripts/end_to_end_eventhub_smoke.py --expected-events $${EXPECTED_EVENTS:-19} $${AGENTS:+--agents}

infra-validate:
	az bicep build --file infra/main.bicep

cloud-smoke-test:
	python3 scripts/cloud_smoke_test.py

load-test:
	set -a; [ ! -f .env ] || . ./.env; set +a; python3 -m simulator.load --match-count $${MATCH_COUNT:-10} --events-per-match $${EVENTS_PER_MATCH:-1000} --rate $${RATE:-500}

chaos-demo:
	python3 scripts/chaos_foundry_unavailable.py
