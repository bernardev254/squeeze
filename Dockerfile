FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN adduser --disabled-password --gecos "" squeeze

COPY pyproject.toml README.md requirements.txt ./
COPY domain ./domain
COPY services ./services
COPY simulator ./simulator
COPY prompts ./prompts
COPY apps ./apps
COPY config ./config

RUN pip install --no-cache-dir -e .
USER squeeze

# API service target
FROM base AS api
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["python", "-m", "uvicorn", "services.match_engine.api:app", "--host", "0.0.0.0", "--port", "8000"]

# Worker processor target
FROM base AS worker
CMD ["python", "-m", "services.cloud.worker"]

# Simulator live feed target
FROM base AS simulator
CMD ["python", "-m", "simulator.live_feed"]
