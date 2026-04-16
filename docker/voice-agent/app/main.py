"""FastAPI entrypoint for the experimental voice agent.

Routes:
    GET  /           serves the static push-to-talk PWA
    GET  /health     liveness probe
    WS   /ws         16 kHz mono PCM audio bidirectional
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import load_settings

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"

app = FastAPI(title="augint-shell voice-agent", version="0.1.0")
settings = load_settings()
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "profile": settings.profile}


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    """Bridge the client audio stream into a Pipecat pipeline task.

    Imports happen inside the handler so the app can start and serve
    `/` and `/health` even in environments where pipecat-ai isn't
    installed (useful while iterating on the PWA without rebuilding).
    """
    await websocket.accept()

    try:
        from pipecat.pipeline.runner import PipelineRunner  # type: ignore[import-not-found]

        from .pipeline import build_pipeline

        task = build_pipeline(settings, websocket)
        runner = PipelineRunner()
        await runner.run(task)
    except ImportError:
        logger.exception("pipecat not installed; closing websocket")
        await websocket.close(code=1011, reason="pipecat not available")
    except Exception:
        logger.exception("pipeline crashed")
        try:
            await websocket.close(code=1011, reason="pipeline error")
        except Exception:
            pass
