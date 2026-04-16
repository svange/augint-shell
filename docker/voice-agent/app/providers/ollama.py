"""Ollama provider adapter for Phase 2.

Thin wrapper around Pipecat's `OLLamaLLMService`. Phase 6 will replace this
with a provider-selection layer that dispatches to Ollama / Anthropic /
OpenAI based on `voice_agent.providers.default`.
"""

from __future__ import annotations

from typing import Any


def build_llm_service(model: str, base_url: str) -> Any:
    """Construct an Ollama LLM service for the Pipecat pipeline.

    Imported lazily so the module can be collected by test tooling
    without pipecat-ai installed.
    """
    from pipecat.services.ollama.llm import OLLamaLLMService  # type: ignore[import-not-found]

    return OLLamaLLMService(model=model, base_url=f"{base_url}/v1")
