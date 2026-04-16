"""Pipecat pipeline construction for Phase 2.

Phase 2 pipeline:

    WS audio in → Silero VAD → Speaches STT (OpenAI-compat) → Ollama LLM
                                                            → Kokoro TTS → WS audio out

Interim transcripts are not available from Pipecat's HTTP-based
`OpenAISTTService`. Final-only is fine for the Phase 2 push-to-talk UX;
barge-in semantics arrive in Phase 3 with VAD-driven `InterruptionFrame`
and `LLMUserAggregator.user_turn_strategies`.
"""

from __future__ import annotations

from typing import Any

from .config import Settings
from .providers.ollama import build_llm_service


def build_pipeline(settings: Settings, websocket: Any) -> Any:
    """Construct and return a configured Pipecat pipeline task.

    Imports happen lazily so this module loads without pipecat-ai in
    environments that only run unit tests.
    """
    from pipecat.audio.vad.silero import SileroVADAnalyzer  # type: ignore[import-not-found]
    from pipecat.pipeline.pipeline import Pipeline  # type: ignore[import-not-found]
    from pipecat.pipeline.task import PipelineParams, PipelineTask  # type: ignore[import-not-found]
    from pipecat.services.kokoro.tts import KokoroTTSService  # type: ignore[import-not-found]
    from pipecat.services.openai.stt import OpenAISTTService  # type: ignore[import-not-found]
    from pipecat.transports.network.websocket_server import (  # type: ignore[import-not-found]
        WebsocketServerParams,
        WebsocketServerTransport,
    )

    transport = WebsocketServerTransport(
        websocket=websocket,
        params=WebsocketServerParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            add_wav_header=False,
        ),
    )

    stt = OpenAISTTService(
        base_url=f"{settings.endpoints.speaches_url}/v1",
        api_key="speaches",
        model="Systran/faster-distil-whisper-large-v3",
    )

    llm = build_llm_service(
        model=settings.active_model(),
        base_url=settings.endpoints.ollama_url,
    )

    tts = KokoroTTSService(
        base_url=f"{settings.endpoints.kokoro_url}/v1",
        api_key="kokoro",
        voice="af_bella",
    )

    pipeline = Pipeline([transport.input(), stt, llm, tts, transport.output()])
    return PipelineTask(pipeline, params=PipelineParams(allow_interruptions=False))
