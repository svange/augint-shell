"""Tests for CLI LLM subcommands."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from ai_shell.cli.__main__ import cli
from ai_shell.cli.commands.llm import _warn_if_low_memory
from ai_shell.defaults import OLLAMA_CONTAINER, WEBUI_CONTAINER


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


@patch("ai_shell.cli.commands.llm.ContainerManager")
@patch("ai_shell.cli.commands.llm.load_config")
class TestLlmCommands:
    def setup_method(self):
        self.runner = CliRunner()

    def test_llm_up(self, mock_config, mock_manager_cls):
        mock_manager = MagicMock()
        mock_manager.config.ollama_port = 11434
        mock_manager.config.webui_port = 3000
        mock_manager.ensure_ollama.return_value = OLLAMA_CONTAINER
        mock_manager.ensure_webui.return_value = WEBUI_CONTAINER
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["llm", "up"])

        assert result.exit_code == 0
        mock_manager.ensure_ollama.assert_called_once()
        mock_manager.ensure_webui.assert_called_once()
        assert "11434" in result.output
        assert "3000" in result.output

    def test_llm_down(self, mock_config, mock_manager_cls):
        mock_manager = MagicMock()
        mock_manager.container_status.side_effect = lambda name: "running"
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["llm", "down"])

        assert result.exit_code == 0
        assert mock_manager.stop_container.call_count == 2

    def test_llm_status_running(self, mock_config, mock_manager_cls):
        mock_manager = MagicMock()
        mock_manager.container_status.return_value = "running"
        mock_manager.exec_in_ollama.return_value = "NAME\tSIZE\nqwen3.5:27b\t16GB"
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["llm", "status"])

        assert result.exit_code == 0
        assert "running" in result.output

    def test_llm_status_not_found(self, mock_config, mock_manager_cls):
        mock_manager = MagicMock()
        mock_manager.container_status.return_value = None
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["llm", "status"])

        assert result.exit_code == 0
        assert "not found" in result.output

    def test_llm_pull(self, mock_config, mock_manager_cls):
        config = MagicMock()
        config.primary_model = "qwen3-coder-next"
        config.fallback_model = "qwen3.5:27b"
        mock_config.return_value = config

        mock_manager = MagicMock()
        mock_manager.config = config
        mock_manager.exec_in_ollama.return_value = "pulling model..."
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["llm", "pull"])

        assert result.exit_code == 0
        # Should pull both models
        assert mock_manager.exec_in_ollama.call_count >= 3  # 2 pulls + 1 list
