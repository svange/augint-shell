# Voice-agent (experimental) — built locally from this directory.
# Not published. Rebuilt on-demand by `ai-shell llm up --voice-agent`.
#
# Layer order favors cache hits: system deps → Python deps → app code.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Runtime deps:
#   - ffmpeg for Pipecat audio I/O / resampling
#   - libsndfile1 for soundfile (openwakeword, kokoro TTS)
#   - curl for container healthchecks when we add them
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pipecat 0.0.99 pinned deliberately. 1.0.0 released 2026-04-14 is too fresh.
# Upgrade in a dedicated ticket after Phase 5 once third-party examples catch up.
#
# mcp[ws] 1.27.0 is what Pipecat's MCPClient wraps; kept pinned.
#
# openai + anthropic clients ship here so Phase 6 provider adapters don't
# require a rebuild.
RUN pip install \
        "pipecat-ai[silero,kokoro,openai,ollama]==0.0.99" \
        "openwakeword" \
        "mcp[ws]==1.27.0" \
        "openai" \
        "anthropic" \
        "fastapi" \
        "uvicorn[standard]" \
        "websockets" \
        "bcrypt" \
        "PyJWT" \
        "httpx" \
        "pydantic-settings" \
        "pyyaml"

COPY app /app/app

# Sqlite lives on a named volume mounted here.
RUN mkdir -p /data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
