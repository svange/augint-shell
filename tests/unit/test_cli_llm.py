"""Tests for CLI LLM subcommands."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from ai_shell.cli.__main__ import cli
from ai_shell.cli.commands.llm import (
    _manifest_exists,
    _parse_model_ref,
    _resolve_stacks,
    _warn_if_low_memory,
)
from ai_shell.defaults import (
    KOKORO_CONTAINER,
    N8N_CONTAINER,
    N8N_DATA_VOLUME,
    OLLAMA_CONTAINER,
    OLLAMA_DATA_VOLUME,
    WEBUI_CONTAINER,
    WEBUI_DATA_VOLUME,
    WHISPER_CONTAINER,
    WHISPER_DATA_VOLUME,
)


def _fake_meminfo(mem_total_kb: int, swap_total_kb: int) -> str:
    return (
        f"MemTotal:       {mem_total_kb} kB\n"
        f"MemFree:        {mem_total_kb // 2} kB\n"
        f"SwapTotal:      {swap_total_kb} kB\n"
        f"SwapFree:       {swap_total_kb} kB\n"
    )


class TestWarnIfLowMemory:
    def test_warns_when_memory_low(self):
        meminfo = _fake_meminfo(22 * 1024 * 1024, 4 * 1024 * 1024)
        output_lines = []
        with (
            patch("ai_shell.cli.commands.llm.Path") as mock_path_cls,
            patch("ai_shell.cli.commands.llm.console") as mock_console,
        ):
            mock_path_cls.return_value.read_text.return_value = meminfo
            _warn_if_low_memory()
            output_lines = [str(c) for c in mock_console.print.call_args_list]

        assert any("Warning" in line for line in output_lines)
        assert any("wslconfig" in line for line in output_lines)

    def test_no_warning_when_memory_sufficient(self):
        meminfo = _fake_meminfo(32 * 1024 * 1024, 8 * 1024 * 1024)
        with (
            patch("ai_shell.cli.commands.llm.Path") as mock_path_cls,
            patch("ai_shell.cli.commands.llm.console") as mock_console,
        ):
            mock_path_cls.return_value.read_text.return_value = meminfo
            _warn_if_low_memory()

        mock_console.print.assert_not_called()

    def test_skips_gracefully_on_non_linux(self):
        with (
            patch("ai_shell.cli.commands.llm.Path") as mock_path_cls,
            patch("ai_shell.cli.commands.llm.console") as mock_console,
        ):
            mock_path_cls.return_value.read_text.side_effect = OSError("No such file")
            _warn_if_low_memory()

        mock_console.print.assert_not_called()


class TestParseModelRef:
    def test_library_no_tag(self):
        assert _parse_model_ref("qwen3-coder") == ("library", "qwen3-coder", "latest")

    def test_library_with_tag(self):
        assert _parse_model_ref("qwen3-coder:30b-a3b-q4_K_M") == (
            "library",
            "qwen3-coder",
            "30b-a3b-q4_K_M",
        )

    def test_namespaced_no_tag(self):
        assert _parse_model_ref("huihui_ai/llama3.3-abliterated") == (
            "huihui_ai",
            "llama3.3-abliterated",
            "latest",
        )

    def test_namespaced_with_tag(self):
        assert _parse_model_ref("huihui_ai/llama3.3-abliterated:q4") == (
            "huihui_ai",
            "llama3.3-abliterated",
            "q4",
        )


class TestResolveStacks:
    def test_no_flags(self):
        assert _resolve_stacks(
            webui=False, voice=False, no_voice=False, whisper=False, n8n=False, all_=False
        ) == (
            False,
            False,
            False,
            False,
        )

    def test_webui_implies_voice(self):
        assert _resolve_stacks(
            webui=True, voice=False, no_voice=False, whisper=False, n8n=False, all_=False
        ) == (
            True,
            True,
            False,
            False,
        )

    def test_voice_standalone(self):
        assert _resolve_stacks(
            webui=False, voice=True, no_voice=False, whisper=False, n8n=False, all_=False
        ) == (
            False,
            True,
            False,
            False,
        )

    def test_no_voice_wins_over_webui(self):
        assert _resolve_stacks(
            webui=True, voice=False, no_voice=True, whisper=False, n8n=False, all_=False
        ) == (
            True,
            False,
            False,
            False,
        )

    def test_no_voice_wins_over_explicit_voice(self):
        assert _resolve_stacks(
            webui=False, voice=True, no_voice=True, whisper=False, n8n=False, all_=False
        ) == (
            False,
            False,
            False,
            False,
        )

    def test_all_enables_everything(self):
        assert _resolve_stacks(
            webui=False, voice=False, no_voice=False, whisper=False, n8n=False, all_=True
        ) == (
            True,
            True,
            True,
            True,
        )

    def test_no_voice_wins_over_all(self):
        assert _resolve_stacks(
            webui=False, voice=False, no_voice=True, whisper=False, n8n=False, all_=True
        ) == (
            True,
            False,
            True,
            True,
        )

    def test_n8n_standalone(self):
        assert _resolve_stacks(
            webui=False, voice=False, no_voice=False, whisper=False, n8n=True, all_=False
        ) == (
            False,
            False,
            False,
            True,
        )

    def test_n8n_does_not_imply_other_stacks(self):
        assert _resolve_stacks(
            webui=False, voice=False, no_voice=False, whisper=False, n8n=True, all_=False
        ) == (
            False,
            False,
            False,
            True,
        )

    def test_whisper_standalone(self):
        assert _resolve_stacks(
            webui=False, voice=False, no_voice=False, whisper=True, n8n=False, all_=False
        ) == (
            False,
            False,
            True,
            False,
        )

    def test_whisper_does_not_imply_other_stacks(self):
        assert _resolve_stacks(
            webui=False, voice=False, no_voice=False, whisper=True, n8n=False, all_=False
        ) == (
            False,
            False,
            True,
            False,
        )


@patch("ai_shell.cli.commands.llm.HTTPSConnection")
class TestManifestExists:
    def test_returns_true_on_200(self, mock_https_cls):
        response = MagicMock()
        response.status = 200
        response.read.return_value = b""
        connection = MagicMock()
        connection.getresponse.return_value = response
        mock_https_cls.return_value = connection

        assert _manifest_exists("qwen3-coder:30b-a3b-q4_K_M") is True
        connection.request.assert_called_once()
        method, path = connection.request.call_args[0][:2]
        assert method == "HEAD"
        assert path == "/v2/library/qwen3-coder/manifests/30b-a3b-q4_K_M"
        connection.close.assert_called_once()

    def test_returns_false_on_404(self, mock_https_cls):
        response = MagicMock()
        response.status = 404
        response.read.return_value = b""
        connection = MagicMock()
        connection.getresponse.return_value = response
        mock_https_cls.return_value = connection

        assert _manifest_exists("qwen3-coder:bogus-tag") is False
        connection.close.assert_called_once()

    def test_returns_none_on_network_error(self, mock_https_cls):
        connection = MagicMock()
        connection.request.side_effect = OSError("boom")
        mock_https_cls.return_value = connection

        assert _manifest_exists("qwen3-coder:30b-a3b-q4_K_M") is None
        connection.close.assert_called_once()

    def test_returns_none_on_unexpected_status(self, mock_https_cls):
        response = MagicMock()
        response.status = 500
        response.read.return_value = b""
        connection = MagicMock()
        connection.getresponse.return_value = response
        mock_https_cls.return_value = connection

        assert _manifest_exists("qwen3-coder:30b-a3b-q4_K_M") is None

    def test_uses_namespace_for_non_library_model(self, mock_https_cls):
        response = MagicMock()
        response.status = 200
        response.read.return_value = b""
        connection = MagicMock()
        connection.getresponse.return_value = response
        mock_https_cls.return_value = connection

        _manifest_exists("huihui_ai/llama3.3-abliterated")
        path = connection.request.call_args[0][1]
        assert path == "/v2/huihui_ai/llama3.3-abliterated/manifests/latest"


def _make_manager_config() -> MagicMock:
    """Build a MagicMock config with all the ports llm commands reference."""
    config = MagicMock()
    config.ollama_port = 11434
    config.webui_port = 3000
    config.kokoro_port = 8880
    config.kokoro_voice = "af_bella"
    config.n8n_port = 5678
    config.whisper_port = 8001
    config.whisper_model = "Systran/faster-distil-whisper-large-v3"
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


@patch("ai_shell.cli.commands.llm.ContainerManager")
@patch("ai_shell.cli.commands.llm.load_config")
class TestLlmCommands:
    def setup_method(self):
        self.runner = CliRunner()

    # ------------------------------------------------------------------
    # up
    # ------------------------------------------------------------------
    def test_llm_up_no_flags_starts_only_ollama(self, mock_config, mock_manager_cls):
        """`llm up` with no flags starts only the base Ollama container."""
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        manager.ensure_ollama.return_value = OLLAMA_CONTAINER
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "up"])

        assert result.exit_code == 0
        manager.ensure_ollama.assert_called_once()
        manager.ensure_webui.assert_not_called()
        manager.ensure_kokoro.assert_not_called()
        assert "11434" in result.output

    def test_llm_up_webui_implies_voice(self, mock_config, mock_manager_cls):
        """--webui brings up Kokoro TTS and wires it as WebUI's backend."""
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "up", "--webui"])

        assert result.exit_code == 0
        manager.ensure_webui.assert_called_once()
        manager.ensure_kokoro.assert_called_once()
        # Voice is implied -> WebUI is pre-wired to TTS.
        assert manager.ensure_webui.call_args.kwargs.get("voice_enabled") is True
        assert "3000" in result.output
        assert "8880" in result.output

    def test_llm_up_webui_no_voice_opts_out_of_tts(self, mock_config, mock_manager_cls):
        """--no-voice is the explicit opt-out and wins over --webui's default."""
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "up", "--webui", "--no-voice"])

        assert result.exit_code == 0
        manager.ensure_webui.assert_called_once()
        manager.ensure_kokoro.assert_not_called()
        assert manager.ensure_webui.call_args.kwargs.get("voice_enabled") is False

    def test_llm_up_voice_flag_standalone(self, mock_config, mock_manager_cls):
        """--voice alone starts Kokoro without WebUI."""
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "up", "--voice"])

        assert result.exit_code == 0
        manager.ensure_kokoro.assert_called_once()
        manager.ensure_webui.assert_not_called()
        assert "Kokoro" in result.output
        assert "8880" in result.output

    def test_llm_up_all_starts_every_stack(self, mock_config, mock_manager_cls):
        """--all enables every currently-supported optional stack."""
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "up", "--all"])

        assert result.exit_code == 0
        manager.ensure_ollama.assert_called_once()
        manager.ensure_webui.assert_called_once()
        manager.ensure_kokoro.assert_called_once()
        manager.ensure_whisper.assert_called_once()
        manager.ensure_n8n.assert_called_once()
        # WebUI is pre-wired to TTS.
        assert manager.ensure_webui.call_args.kwargs.get("voice_enabled") is True
        assert "5678" in result.output
        assert "8001" in result.output

    def test_llm_up_whisper_flag_standalone(self, mock_config, mock_manager_cls):
        """--whisper alone starts Speaches without WebUI or Kokoro."""
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "up", "--whisper"])

        assert result.exit_code == 0
        manager.ensure_whisper.assert_called_once()
        manager.ensure_webui.assert_not_called()
        manager.ensure_kokoro.assert_not_called()
        assert "Speaches" in result.output
        assert "8001" in result.output

    def test_llm_up_n8n_flag_standalone(self, mock_config, mock_manager_cls):
        """--n8n alone starts n8n without WebUI or Kokoro."""
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "up", "--n8n"])

        assert result.exit_code == 0
        manager.ensure_n8n.assert_called_once()
        manager.ensure_webui.assert_not_called()
        manager.ensure_kokoro.assert_not_called()
        assert "n8n" in result.output
        assert "5678" in result.output

    # ------------------------------------------------------------------
    # down
    # ------------------------------------------------------------------
    def test_llm_down_no_flags_stops_only_ollama(self, mock_config, mock_manager_cls):
        manager = MagicMock()
        manager.container_status.return_value = "running"
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "down"])

        assert result.exit_code == 0
        stopped = [c.args[0] for c in manager.stop_container.call_args_list]
        assert stopped == [OLLAMA_CONTAINER]

    def test_llm_down_all_stops_every_container(self, mock_config, mock_manager_cls):
        manager = MagicMock()
        manager.container_status.return_value = "running"
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "down", "--all"])

        assert result.exit_code == 0
        stopped = [c.args[0] for c in manager.stop_container.call_args_list]
        for name in (
            OLLAMA_CONTAINER,
            WEBUI_CONTAINER,
            KOKORO_CONTAINER,
            WHISPER_CONTAINER,
            N8N_CONTAINER,
        ):
            assert name in stopped

    def test_llm_down_whisper_only_stops_ollama_and_whisper(self, mock_config, mock_manager_cls):
        manager = MagicMock()
        manager.container_status.return_value = "running"
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "down", "--whisper"])

        assert result.exit_code == 0
        stopped = [c.args[0] for c in manager.stop_container.call_args_list]
        assert OLLAMA_CONTAINER in stopped
        assert WHISPER_CONTAINER in stopped
        assert WEBUI_CONTAINER not in stopped
        assert KOKORO_CONTAINER not in stopped
        assert N8N_CONTAINER not in stopped

    def test_llm_down_n8n_only_stops_ollama_and_n8n(self, mock_config, mock_manager_cls):
        manager = MagicMock()
        manager.container_status.return_value = "running"
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "down", "--n8n"])

        assert result.exit_code == 0
        stopped = [c.args[0] for c in manager.stop_container.call_args_list]
        assert OLLAMA_CONTAINER in stopped
        assert N8N_CONTAINER in stopped
        assert WEBUI_CONTAINER not in stopped
        assert KOKORO_CONTAINER not in stopped

    def test_llm_down_webui_no_voice_leaves_kokoro_alone(self, mock_config, mock_manager_cls):
        """--webui --no-voice stops WebUI but leaves Kokoro running."""
        manager = MagicMock()
        manager.container_status.return_value = "running"
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "down", "--webui", "--no-voice"])

        assert result.exit_code == 0
        stopped = [c.args[0] for c in manager.stop_container.call_args_list]
        assert OLLAMA_CONTAINER in stopped
        assert WEBUI_CONTAINER in stopped
        assert KOKORO_CONTAINER not in stopped

    # ------------------------------------------------------------------
    # clean
    # ------------------------------------------------------------------
    def test_llm_clean_no_flags_removes_only_ollama_container(self, mock_config, mock_manager_cls):
        manager = MagicMock()
        manager.container_status.return_value = "running"
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "clean", "--yes"])

        assert result.exit_code == 0
        removed = [c.args[0] for c in manager.remove_container.call_args_list]
        assert removed == [OLLAMA_CONTAINER]
        # --wipe not set: volumes must be preserved.
        manager.remove_volume.assert_not_called()

    def test_llm_clean_all_wipe_removes_all_containers_and_volumes(
        self, mock_config, mock_manager_cls
    ):
        """`clean --all --wipe` is the full-reset path."""
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        manager.container_status.return_value = "running"
        manager.remove_volume.return_value = True
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "clean", "--all", "--wipe", "--yes"])

        assert result.exit_code == 0
        removed_containers = [c.args[0] for c in manager.remove_container.call_args_list]
        for name in (
            OLLAMA_CONTAINER,
            WEBUI_CONTAINER,
            KOKORO_CONTAINER,
            WHISPER_CONTAINER,
            N8N_CONTAINER,
        ):
            assert name in removed_containers

        removed_volumes = [c.args[0] for c in manager.remove_volume.call_args_list]
        assert OLLAMA_DATA_VOLUME in removed_volumes
        assert WEBUI_DATA_VOLUME in removed_volumes
        assert WHISPER_DATA_VOLUME in removed_volumes
        assert N8N_DATA_VOLUME in removed_volumes

    def test_llm_clean_whisper_removes_container_only(self, mock_config, mock_manager_cls):
        """--whisper without --wipe removes the container but preserves the cache."""
        manager = MagicMock()
        manager.container_status.return_value = "running"
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "clean", "--whisper", "--yes"])

        assert result.exit_code == 0
        removed = [c.args[0] for c in manager.remove_container.call_args_list]
        assert OLLAMA_CONTAINER in removed
        assert WHISPER_CONTAINER in removed
        manager.remove_volume.assert_not_called()

    def test_llm_clean_whisper_wipe_removes_cache_volume(self, mock_config, mock_manager_cls):
        """--whisper --wipe removes the cache volume alongside Ollama's."""
        manager = MagicMock()
        manager.container_status.return_value = "running"
        manager.remove_volume.return_value = True
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "clean", "--whisper", "--wipe", "--yes"])

        assert result.exit_code == 0
        removed_volumes = [c.args[0] for c in manager.remove_volume.call_args_list]
        assert OLLAMA_DATA_VOLUME in removed_volumes
        assert WHISPER_DATA_VOLUME in removed_volumes
        assert WEBUI_DATA_VOLUME not in removed_volumes
        assert N8N_DATA_VOLUME not in removed_volumes

    def test_llm_clean_webui_wipe_only_removes_webui_volume(self, mock_config, mock_manager_cls):
        """--wipe without --all must not touch unrelated stack volumes."""
        manager = MagicMock()
        manager.container_status.return_value = "running"
        manager.remove_volume.return_value = True
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "clean", "--webui", "--wipe", "--yes"])

        assert result.exit_code == 0
        removed_volumes = [c.args[0] for c in manager.remove_volume.call_args_list]
        # Base Ollama volume is always removed with --wipe.
        assert OLLAMA_DATA_VOLUME in removed_volumes
        assert WEBUI_DATA_VOLUME in removed_volumes

    def test_llm_clean_skips_missing_containers(self, mock_config, mock_manager_cls):
        manager = MagicMock()
        manager.container_status.return_value = None
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "clean", "--yes"])

        assert result.exit_code == 0
        manager.remove_container.assert_not_called()
        assert "Not found" in result.output

    def test_llm_clean_aborts_without_confirmation(self, mock_config, mock_manager_cls):
        manager = MagicMock()
        mock_manager_cls.return_value = manager

        # Simulate user typing "n" at the prompt.
        result = self.runner.invoke(cli, ["llm", "clean"], input="n\n")

        assert result.exit_code == 0
        assert "Aborted" in result.output
        manager.remove_container.assert_not_called()
        manager.remove_volume.assert_not_called()

    def test_llm_clean_wipe_confirmation_mentions_data_loss(self, mock_config, mock_manager_cls):
        manager = MagicMock()
        manager.container_status.return_value = None
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "clean", "--wipe"], input="y\n")

        assert result.exit_code == 0
        assert "deleted" in result.output.lower()

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------
    def test_llm_status_always_shows_every_stack(self, mock_config, mock_manager_cls):
        """`llm status` must render every known container regardless of flags."""
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        manager.container_status.return_value = "running"
        manager.exec_in_ollama.return_value = "NAME\tSIZE\nqwen3-coder\t16GB"
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "status"])

        assert result.exit_code == 0
        assert "Base stack" in result.output
        assert "WebUI stack" in result.output
        assert "Voice stack" in result.output
        assert "Speaches stack" in result.output
        assert "n8n stack" in result.output
        assert "http://localhost:11434" in result.output
        assert "http://localhost:11434/v1" in result.output
        assert "http://localhost:3000" in result.output
        assert "http://localhost:8880" in result.output
        assert "http://localhost:8001" in result.output
        assert "/v1/audio/transcriptions" in result.output
        assert "http://localhost:5678" in result.output
        # Configured model + context size.
        assert "qwen3-coder:30b-a3b-q4_K_M" in result.output
        assert "32768" in result.output

    def test_llm_status_marks_absent_stacks(self, mock_config, mock_manager_cls):
        """When containers are absent, status must flag each URL as not running."""
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        manager.container_status.return_value = None
        mock_manager_cls.return_value = manager

        result = self.runner.invoke(cli, ["llm", "status"])

        assert result.exit_code == 0
        assert "absent" in result.output
        assert "not running" in result.output

    # ------------------------------------------------------------------
    # pull
    # ------------------------------------------------------------------
    def test_llm_pull(self, mock_config, mock_manager_cls):
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        manager.exec_in_ollama.return_value = "pulling model..."
        mock_manager_cls.return_value = manager

        with patch("ai_shell.cli.commands.llm._manifest_exists", return_value=True):
            result = self.runner.invoke(cli, ["llm", "pull"])

        assert result.exit_code == 0
        # Should pull all 4 slots + the trailing `ollama list`
        assert manager.exec_in_ollama.call_count >= 5  # 4 pulls + 1 list

    def test_llm_pull_aborts_on_missing_tag(self, mock_config, mock_manager_cls):
        config = _make_manager_config()
        config.primary_coding_model = "qwen3-coder:bogus-tag"
        config.models_to_pull = [
            config.primary_chat_model,
            config.secondary_chat_model,
            config.primary_coding_model,
            config.secondary_coding_model,
        ]
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        mock_manager_cls.return_value = manager

        # Primary coding is missing, others exist.
        def fake_probe(ref: str) -> bool:
            return not ref.endswith("bogus-tag")

        with patch("ai_shell.cli.commands.llm._manifest_exists", side_effect=fake_probe):
            result = self.runner.invoke(cli, ["llm", "pull"])

        assert result.exit_code != 0
        assert "not found" in result.output
        assert "qwen3-coder:bogus-tag" in result.output
        # Must not have started pulling anything.
        manager.exec_in_ollama.assert_not_called()

    def test_llm_pull_proceeds_when_registry_unreachable(self, mock_config, mock_manager_cls):
        config = _make_manager_config()
        mock_config.return_value = config

        manager = MagicMock()
        manager.config = config
        manager.exec_in_ollama.return_value = "pulling model..."
        mock_manager_cls.return_value = manager

        # None = probe couldn't complete; must not block the pull.
        with patch("ai_shell.cli.commands.llm._manifest_exists", return_value=None):
            result = self.runner.invoke(cli, ["llm", "pull"])

        assert result.exit_code == 0
        assert manager.exec_in_ollama.call_count >= 3
