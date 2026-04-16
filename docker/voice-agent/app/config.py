"""Voice-agent runtime config, read from /config/voice-agent.yaml inside the container.

The container-side schema intentionally mirrors the host-side `VoiceAgentConfig`
in `src/ai_shell/config.py`. Fields the container actually consumes in Phase 2
are `ollama_url`, `speaches_url`, `kokoro_url`, and the default provider's model.
Everything else is a placeholder for Phases 3-6 so config edits don't crash
the container when users start enabling more features.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(os.environ.get("VOICE_AGENT_CONFIG", "/config/voice-agent.yaml"))


@dataclass
class Endpoints:
    ollama_url: str = "http://augint-shell-ollama:11434"
    speaches_url: str = "http://augint-shell-whisper:8000"
    kokoro_url: str = "http://augint-shell-kokoro:8880"


@dataclass
class ModelProfile:
    primary: str = ""
    secondary: str = ""


@dataclass
class Settings:
    port: int = 8000
    domain: str = ""
    profile: str = "resident"
    profiles: dict[str, ModelProfile] = field(
        default_factory=lambda: {
            "resident": ModelProfile(
                primary="qwen3.5:14b-instruct",
                secondary="huihui_ai/qwen3.5-abliterated:14b",
            ),
            "swap": ModelProfile(
                primary="qwen3.5:27b",
                secondary="dolphin3:8b",
            ),
        }
    )
    endpoints: Endpoints = field(default_factory=Endpoints)

    def active_model(self) -> str:
        profile = self.profiles.get(self.profile) or ModelProfile()
        return profile.primary or "qwen3.5:14b-instruct"


def _load_raw() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open(encoding="utf-8") as fp:
        return yaml.safe_load(fp) or {}


def load_settings() -> Settings:
    raw = _load_raw()
    settings = Settings()
    if "port" in raw:
        settings.port = int(raw["port"])
    if "domain" in raw:
        settings.domain = str(raw["domain"])
    if "profile" in raw:
        settings.profile = str(raw["profile"])
    if isinstance(raw.get("profiles"), dict):
        for name, entry in raw["profiles"].items():
            if isinstance(entry, dict):
                settings.profiles[name] = ModelProfile(
                    primary=str(entry.get("primary", "")),
                    secondary=str(entry.get("secondary", "")),
                )
    if isinstance(raw.get("endpoints"), dict):
        endpoints = raw["endpoints"]
        if "ollama_url" in endpoints:
            settings.endpoints.ollama_url = str(endpoints["ollama_url"])
        if "speaches_url" in endpoints:
            settings.endpoints.speaches_url = str(endpoints["speaches_url"])
        if "kokoro_url" in endpoints:
            settings.endpoints.kokoro_url = str(endpoints["kokoro_url"])
    return settings
