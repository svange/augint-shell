"""Tests for CLI tool subcommands."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from ai_shell.cli.__main__ import cli


@patch("ai_shell.cli.commands.tools.ContainerManager")
@patch("ai_shell.cli.commands.tools.load_config")
class TestToolCommands:
    def setup_method(self):
        self.runner = CliRunner()

    def test_claude_command(self, mock_config, mock_manager_cls):
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        # exec_interactive calls os.execvp which never returns,
        # so we just verify it's called correctly
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["claude"])

        mock_manager.ensure_dev_container.assert_called_once()
        mock_manager.exec_interactive.assert_called_once()
        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert cmd == ["claude"]

    def test_claude_x_command(self, mock_config, mock_manager_cls):
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["claude-x"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert cmd == ["claude", "--dangerously-skip-permissions", "-c"]

    def test_codex_command(self, mock_config, mock_manager_cls):
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["codex"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert "codex" in cmd
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd

    def test_shell_command(self, mock_config, mock_manager_cls):
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["shell"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert cmd == ["/bin/bash"]

    def test_claude_with_extra_args(self, mock_config, mock_manager_cls):
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["claude", "--", "--debug"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert cmd == ["claude", "--debug"]

    def test_aider_passes_model_and_env(self, mock_config, mock_manager_cls):
        config = MagicMock()
        config.aider_model = "ollama_chat/qwen3.5:27b"
        mock_config.return_value = config

        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.config = config
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["aider"])

        call_args = mock_manager.exec_interactive.call_args
        cmd = call_args[0][1]
        extra_env = call_args[1].get("extra_env", {})

        assert "--model" in cmd
        assert "ollama_chat/qwen3.5:27b" in cmd
        assert "--yes-always" in cmd
        assert extra_env["OLLAMA_API_BASE"] == "http://host.docker.internal:11434"

    def test_version_flag(self, mock_config, mock_manager_cls):
        result = self.runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "ai-shell" in result.output
