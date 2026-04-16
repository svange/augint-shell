"""Tests for CLI LLM subcommands."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from ai_shell.cli.__main__ import cli
from ai_shell.cli.commands.llm import (
    _manifest_exists,
    _parse_model_ref,
    _warn_if_low_memory,
)
from ai_shell.defaults import (
    LOBECHAT_CONTAINER,
    OLLAMA_CONTAINER,
    OLLAMA_DATA_VOLUME,
    WEBUI_CONTAINER,
    WEBUI_DATA_VOLUME,
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


@patch("ai_shell.cli.commands.llm.ContainerManager")
@patch("ai_shell.cli.commands.llm.load_config")
class TestLlmCommands:
    def setup_method(self):
        self.runner = CliRunner()

    def test_llm_up(self, mock_config, mock_manager_cls):
        mock_manager = MagicMock()
        mock_manager.config.ollama_port = 11434
        mock_manager.config.webui_port = 3000
        mock_manager.config.lobechat_port = 3210
        mock_manager.ensure_ollama.return_value = OLLAMA_CONTAINER
        mock_manager.ensure_webui.return_value = WEBUI_CONTAINER
        mock_manager.ensure_lobechat.return_value = LOBECHAT_CONTAINER
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["llm", "up"])

        assert result.exit_code == 0
        mock_manager.ensure_ollama.assert_called_once()
        mock_manager.ensure_webui.assert_called_once()
        mock_manager.ensure_lobechat.assert_called_once()
        assert "11434" in result.output
        assert "3000" in result.output
        assert "3210" in result.output
        assert "LobeChat" in result.output

    def test_llm_down(self, mock_config, mock_manager_cls):
        mock_manager = MagicMock()
        mock_manager.container_status.side_effect = lambda name: "running"
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["llm", "down"])

        assert result.exit_code == 0
        assert mock_manager.stop_container.call_count == 3
        stopped_names = [c.args[0] for c in mock_manager.stop_container.call_args_list]
        assert LOBECHAT_CONTAINER in stopped_names
        assert WEBUI_CONTAINER in stopped_names
        assert OLLAMA_CONTAINER in stopped_names

    def test_llm_clean_removes_containers_preserves_volumes(self, mock_config, mock_manager_cls):
        mock_manager = MagicMock()
        mock_manager.container_status.return_value = "running"
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["llm", "clean", "--yes"])

        assert result.exit_code == 0
        assert mock_manager.remove_container.call_count == 3
        removed = [c.args[0] for c in mock_manager.remove_container.call_args_list]
        assert LOBECHAT_CONTAINER in removed
        assert WEBUI_CONTAINER in removed
        assert OLLAMA_CONTAINER in removed
        # Volumes must be preserved without --volumes flag.
        mock_manager.remove_volume.assert_not_called()

    def test_llm_clean_with_volumes_removes_both(self, mock_config, mock_manager_cls):
        mock_manager = MagicMock()
        mock_manager.container_status.return_value = "running"
        mock_manager.remove_volume.return_value = True
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["llm", "clean", "--volumes", "--yes"])

        assert result.exit_code == 0
        assert mock_manager.remove_container.call_count == 3
        removed_volumes = [c.args[0] for c in mock_manager.remove_volume.call_args_list]
        assert OLLAMA_DATA_VOLUME in removed_volumes
        assert WEBUI_DATA_VOLUME in removed_volumes

    def test_llm_clean_skips_missing_containers(self, mock_config, mock_manager_cls):
        mock_manager = MagicMock()
        mock_manager.container_status.return_value = None
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["llm", "clean", "--yes"])

        assert result.exit_code == 0
        mock_manager.remove_container.assert_not_called()
        assert "Not found" in result.output

    def test_llm_clean_aborts_without_confirmation(self, mock_config, mock_manager_cls):
        mock_manager = MagicMock()
        mock_manager_cls.return_value = mock_manager

        # Simulate user typing "n" at the prompt.
        result = self.runner.invoke(cli, ["llm", "clean"], input="n\n")

        assert result.exit_code == 0
        assert "Aborted" in result.output
        mock_manager.remove_container.assert_not_called()
        mock_manager.remove_volume.assert_not_called()

    def test_llm_clean_confirmation_mentions_volumes_when_flag_set(
        self, mock_config, mock_manager_cls
    ):
        mock_manager = MagicMock()
        mock_manager.container_status.return_value = None
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["llm", "clean", "--volumes"], input="y\n")

        assert result.exit_code == 0
        assert "models will be deleted" in result.output

    def test_llm_status_running(self, mock_config, mock_manager_cls):
        config = MagicMock()
        config.ollama_port = 11434
        config.webui_port = 3000
        config.lobechat_port = 3210
        config.primary_model = "qwen3-coder:30b-a3b-q4_K_M"
        config.fallback_model = "huihui_ai/llama3.3-abliterated"
        config.context_size = 32768
        mock_config.return_value = config

        mock_manager = MagicMock()
        mock_manager.config = config
        mock_manager.container_status.return_value = "running"
        mock_manager.exec_in_ollama.return_value = (
            "NAME\tSIZE\nhuihui_ai/llama3.3-abliterated\t16GB"
        )
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["llm", "status"])

        assert result.exit_code == 0
        assert "running" in result.output
        assert "http://localhost:11434" in result.output
        assert "http://localhost:11434/v1" in result.output
        assert "http://localhost:3000" in result.output
        assert "http://localhost:3210" in result.output
        assert "LobeChat" in result.output
        assert "recommended" in result.output
        assert "qwen3-coder:30b-a3b-q4_K_M" in result.output
        assert "32768" in result.output

    def test_llm_status_not_found(self, mock_config, mock_manager_cls):
        config = MagicMock()
        config.ollama_port = 11434
        config.webui_port = 3000
        config.lobechat_port = 3210
        config.primary_model = "qwen3-coder:30b-a3b-q4_K_M"
        config.fallback_model = "huihui_ai/llama3.3-abliterated"
        config.context_size = 32768
        mock_config.return_value = config

        mock_manager = MagicMock()
        mock_manager.config = config
        mock_manager.container_status.return_value = None
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["llm", "status"])

        assert result.exit_code == 0
        assert "not found" in result.output
        assert "http://localhost:11434" in result.output
        assert "http://localhost:3210" in result.output
        assert "LobeChat" in result.output
        assert "not running" in result.output

    def test_llm_pull(self, mock_config, mock_manager_cls):
        config = MagicMock()
        config.primary_model = "qwen3-coder:30b-a3b-q4_K_M"
        config.fallback_model = "huihui_ai/llama3.3-abliterated"
        mock_config.return_value = config

        mock_manager = MagicMock()
        mock_manager.config = config
        mock_manager.exec_in_ollama.return_value = "pulling model..."
        mock_manager_cls.return_value = mock_manager

        with patch("ai_shell.cli.commands.llm._manifest_exists", return_value=True):
            result = self.runner.invoke(cli, ["llm", "pull"])

        assert result.exit_code == 0
        # Should pull both models
        assert mock_manager.exec_in_ollama.call_count >= 3  # 2 pulls + 1 list

    def test_llm_pull_aborts_on_missing_tag(self, mock_config, mock_manager_cls):
        config = MagicMock()
        config.primary_model = "qwen3-coder:bogus-tag"
        config.fallback_model = "huihui_ai/llama3.3-abliterated"
        mock_config.return_value = config

        mock_manager = MagicMock()
        mock_manager.config = config
        mock_manager_cls.return_value = mock_manager

        # Primary is missing, fallback exists.
        def fake_probe(ref: str) -> bool:
            return not ref.endswith("bogus-tag")

        with patch("ai_shell.cli.commands.llm._manifest_exists", side_effect=fake_probe):
            result = self.runner.invoke(cli, ["llm", "pull"])

        assert result.exit_code != 0
        assert "not found" in result.output
        assert "qwen3-coder:bogus-tag" in result.output
        # Must not have started pulling anything.
        mock_manager.exec_in_ollama.assert_not_called()

    def test_llm_pull_proceeds_when_registry_unreachable(self, mock_config, mock_manager_cls):
        config = MagicMock()
        config.primary_model = "qwen3-coder:30b-a3b-q4_K_M"
        config.fallback_model = "huihui_ai/llama3.3-abliterated"
        mock_config.return_value = config

        mock_manager = MagicMock()
        mock_manager.config = config
        mock_manager.exec_in_ollama.return_value = "pulling model..."
        mock_manager_cls.return_value = mock_manager

        # None = probe couldn't complete; must not block the pull.
        with patch("ai_shell.cli.commands.llm._manifest_exists", return_value=None):
            result = self.runner.invoke(cli, ["llm", "pull"])

        assert result.exit_code == 0
        assert mock_manager.exec_in_ollama.call_count >= 3
