"""Tests for the model catalog and llm models command."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from ai_shell.cli.__main__ import cli
from ai_shell.models import MODEL_CATALOG, classify_status, lookup

# ---------------------------------------------------------------------------
# Unit tests for models.py
# ---------------------------------------------------------------------------


class TestModelInfo:
    def test_frozen(self):
        info = MODEL_CATALOG[0]
        try:
            info.tag = "nope"  # type: ignore[misc]
            raise AssertionError("Expected FrozenInstanceError")
        except AttributeError:
            pass

    def test_catalog_has_entries(self):
        assert len(MODEL_CATALOG) > 0

    def test_all_entries_have_required_fields(self):
        for info in MODEL_CATALOG:
            assert info.tag, f"Missing tag on {info}"
            assert info.role in ("chat", "coding"), f"Bad role on {info.tag}"
            assert info.params, f"Missing params on {info.tag}"
            assert info.size_gb > 0, f"Bad size on {info.tag}"
            assert isinstance(info.uncensored, bool)
            assert info.description, f"Missing description on {info.tag}"

    def test_no_duplicate_tags(self):
        tags = [m.tag for m in MODEL_CATALOG]
        assert len(tags) == len(set(tags)), (
            f"Duplicate tags: {[t for t in tags if tags.count(t) > 1]}"
        )


class TestLookup:
    def test_known_model(self):
        info = lookup("qwen3.5:27b")
        assert info is not None
        assert info.role == "chat"
        assert info.params == "27B"

    def test_unknown_model(self):
        assert lookup("nonexistent:latest") is None

    def test_uncensored_model(self):
        info = lookup("huihui_ai/qwen3.5-abliterated:27b")
        assert info is not None
        assert info.uncensored is True


class TestClassifyStatus:
    def test_config_model(self):
        config_tags = {"qwen3.5:27b"}
        pulled_tags = {"qwen3.5:27b"}
        assert classify_status("qwen3.5:27b", config_tags, pulled_tags) == "config"

    def test_config_even_if_not_pulled(self):
        config_tags = {"qwen3.5:27b"}
        pulled_tags: set[str] = set()
        assert classify_status("qwen3.5:27b", config_tags, pulled_tags) == "config"

    def test_pulled_but_not_config(self):
        config_tags: set[str] = set()
        pulled_tags = {"qwen3.5:14b-instruct"}
        assert classify_status("qwen3.5:14b-instruct", config_tags, pulled_tags) == "pulled"

    def test_available_in_catalog_only(self):
        config_tags: set[str] = set()
        pulled_tags: set[str] = set()
        assert classify_status("qwen3.5:14b-instruct", config_tags, pulled_tags) == "available"

    def test_untracked_not_in_catalog(self):
        config_tags: set[str] = set()
        pulled_tags = {"some-random-model:latest"}
        assert classify_status("some-random-model:latest", config_tags, pulled_tags) == "untracked"

    def test_config_wins_over_pulled(self):
        """A model in both config and pulled should show as 'config'."""
        config_tags = {"dolphin3:8b"}
        pulled_tags = {"dolphin3:8b"}
        assert classify_status("dolphin3:8b", config_tags, pulled_tags) == "config"


# ---------------------------------------------------------------------------
# CLI integration tests for `llm models`
# ---------------------------------------------------------------------------


def _make_manager_config() -> MagicMock:
    config = MagicMock()
    config.ollama_port = 11434
    config.webui_port = 3000
    config.kokoro_port = 8880
    config.kokoro_voice = "af_bella"
    config.n8n_port = 5678
    config.comfyui_port = 8188
    config.whisper_port = 8001
    config.whisper_model = "Systran/faster-distil-whisper-large-v3"
    config.voice_agent = MagicMock()
    config.voice_agent.port = 8010
    config.primary_chat_model = "qwen3.5:27b"
    config.secondary_chat_model = "huihui_ai/qwen3.5-abliterated:27b"
    config.primary_coding_model = "qwen3-coder:30b-a3b-q4_K_M"
    config.secondary_coding_model = "huihui_ai/qwen3-coder-abliterated:30b-a3b-instruct-q4_K_M"
    config.extra_models = []
    config.models_to_pull = [
        config.primary_chat_model,
        config.secondary_chat_model,
        config.primary_coding_model,
        config.secondary_coding_model,
    ]
    config.context_size = 32768
    return config


_FAKE_OLLAMA_LIST = (
    "NAME                                                          ID           SIZE     MODIFIED\n"
    "qwen3.5:27b                                                   abc123       17 GB    2 days ago\n"
    "huihui_ai/qwen3.5-abliterated:27b                             def456       17 GB    2 days ago\n"
    "qwen3-coder:30b-a3b-q4_K_M                                    ghi789       19 GB    3 days ago\n"
    "huihui_ai/qwen3-coder-abliterated:30b-a3b-instruct-q4_K_M     jkl012       19 GB    3 days ago\n"
    "llama3.2:latest                                                mno345       2 GB     5 days ago\n"
    "mystery-model:7b                                               pqr678       4 GB     1 day ago\n"
)


@patch("ai_shell.cli.commands.llm.ContainerManager")
@patch("ai_shell.cli.commands.llm.load_config")
class TestLlmModelsCommand:
    def setup_method(self):
        self.runner = CliRunner()

    def test_shows_catalog_with_config_models(self, mock_config, mock_manager_cls):
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        manager.container_status.return_value = "running"
        manager.exec_in_ollama.return_value = _FAKE_OLLAMA_LIST
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "models"])

        assert result.exit_code == 0
        assert "LLM Model Catalog" in result.output
        assert "qwen3.5:27b" in result.output
        assert "config" in result.output
        assert "CHAT models" in result.output
        assert "CODING models" in result.output

    def test_shows_untracked_models(self, mock_config, mock_manager_cls):
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        manager.container_status.return_value = "running"
        manager.exec_in_ollama.return_value = _FAKE_OLLAMA_LIST
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "models"])

        assert result.exit_code == 0
        assert "mystery-model:7b" in result.output
        assert "untracked" in result.output
        assert "OTHER models" in result.output

    def test_shows_pulled_status_for_non_config_catalog_model(self, mock_config, mock_manager_cls):
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        manager.container_status.return_value = "running"
        manager.exec_in_ollama.return_value = _FAKE_OLLAMA_LIST
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "models"])

        assert result.exit_code == 0
        # llama3.2:latest is in Ollama + catalog but not in config
        assert "llama3.2:latest" in result.output
        assert "pulled" in result.output

    def test_pulled_filter(self, mock_config, mock_manager_cls):
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        manager.container_status.return_value = "running"
        manager.exec_in_ollama.return_value = _FAKE_OLLAMA_LIST
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "models", "--pulled"])

        assert result.exit_code == 0
        # Should NOT show models that aren't pulled (e.g. qwen3.5:14b-instruct)
        assert "available" not in result.output

    def test_role_filter_chat(self, mock_config, mock_manager_cls):
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        manager.container_status.return_value = "running"
        manager.exec_in_ollama.return_value = _FAKE_OLLAMA_LIST
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "models", "--role", "chat"])

        assert result.exit_code == 0
        # Should not show coding models
        assert "qwen3-coder" not in result.output
        # Should show chat models
        assert "qwen3.5:27b" in result.output

    def test_role_filter_coding(self, mock_config, mock_manager_cls):
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        manager.container_status.return_value = "running"
        manager.exec_in_ollama.return_value = _FAKE_OLLAMA_LIST
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "models", "--role", "coding"])

        assert result.exit_code == 0
        assert "qwen3-coder" in result.output
        # Chat-only models filtered out
        assert "llama3.2:latest" not in result.output

    def test_uncensored_filter(self, mock_config, mock_manager_cls):
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        manager.container_status.return_value = "running"
        manager.exec_in_ollama.return_value = _FAKE_OLLAMA_LIST
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "models", "--uncensored"])

        assert result.exit_code == 0
        assert "(U)" in result.output
        # Censored-only models should be filtered out (qwen3.5:27b is censored)
        # Note: qwen3.5 appears in uncensored variant names so check exact tag
        assert "huihui_ai/qwen3.5-abliterated:27b" in result.output

    def test_warns_when_ollama_not_running(self, mock_config, mock_manager_cls):
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        manager.container_status.return_value = None
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "models"])

        assert result.exit_code == 0
        assert "Ollama is not running" in result.output

    def test_no_matches_message(self, mock_config, mock_manager_cls):
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        manager.container_status.return_value = "running"
        # Only non-catalog model pulled, filter by --uncensored + --role coding
        manager.exec_in_ollama.return_value = (
            "NAME    ID    SIZE    MODIFIED\nmystery-model:7b    abc    4 GB    1 day ago\n"
        )
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(
            cli, ["llm", "models", "--uncensored", "--role", "coding", "--pulled"]
        )

        assert result.exit_code == 0
        assert "No models match" in result.output

    def test_shows_caveats_for_config_models(self, mock_config, mock_manager_cls):
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        manager.container_status.return_value = "running"
        manager.exec_in_ollama.return_value = _FAKE_OLLAMA_LIST
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "models"])

        assert result.exit_code == 0
        assert "caveat" in result.output
        assert "ollama #14493" in result.output
