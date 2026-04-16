"""Tests for repository OpenCode configuration."""

import json
from pathlib import Path


def test_opencode_uses_27b_local_model_only():
    config_path = Path(__file__).resolve().parents[2] / "opencode.json"
    config = json.loads(config_path.read_text())

    assert config["model"] == "ollama/qwen3.5:27b"
    assert "qwen3-coder-next" not in config["provider"]["ollama"]["models"]
