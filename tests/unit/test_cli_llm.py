"""Tests for CLI LLM subcommands."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from ai_shell.cli.__main__ import cli
from ai_shell.defaults import OLLAMA_CONTAINER, WEBUI_CONTAINER


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
        config.primary_model = "qwen3.5:27b"
        config.fallback_model = "qwen3-coder-next"
        mock_config.return_value = config

        mock_manager = MagicMock()
        mock_manager.config = config
        mock_manager.exec_in_ollama.return_value = "pulling model..."
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["llm", "pull"])

        assert result.exit_code == 0
        # Should pull both models
        assert mock_manager.exec_in_ollama.call_count >= 3  # 2 pulls + 1 list
