"""Tests for CLI tool subcommands."""

from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from ai_shell.cli.__main__ import cli

TEST_EXEC_ENV = {
    "AWS_PROFILE": "",
    "AWS_REGION": "us-east-1",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_PAGER": "",
    "GH_TOKEN": "test-token",
    "GITHUB_TOKEN": "test-token",
    "IS_SANDBOX": "1",
}


@patch("ai_shell.cli.commands.tools._check_bedrock_access")
@patch("ai_shell.cli.commands.tools.build_dev_environment")
@patch("ai_shell.cli.commands.tools.ContainerManager")
@patch("ai_shell.cli.commands.tools.load_config")
class TestToolCommands:
    def setup_method(self):
        self.runner = CliRunner()

    def test_claude_default_uses_permissive_with_continue(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        # run_interactive succeeds (exit code 0, took 30s)
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["claude"])

        mock_manager.run_interactive.assert_called_once()
        cmd = mock_manager.run_interactive.call_args[0][1]
        assert cmd == ["claude", "--dangerously-skip-permissions", "-c"]
        assert mock_manager.run_interactive.call_args[1]["extra_env"] == TEST_EXEC_ENV
        # Should NOT call exec_interactive (no retry needed)
        mock_manager.exec_interactive.assert_not_called()
        assert result.exit_code == 0

    def test_claude_retry_on_fast_failure(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        # run_interactive fails fast (no prior conversation)
        mock_manager.run_interactive.return_value = (1, 1.0)
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["claude"])

        # First tried with -c
        cmd_continue = mock_manager.run_interactive.call_args[0][1]
        assert cmd_continue == ["claude", "--dangerously-skip-permissions", "-c"]
        # Then retried without -c
        cmd_fresh = mock_manager.exec_interactive.call_args[0][1]
        assert cmd_fresh == ["claude", "--dangerously-skip-permissions"]
        assert mock_manager.exec_interactive.call_args[1]["extra_env"] == TEST_EXEC_ENV

    def test_claude_no_retry_on_slow_failure(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        # run_interactive fails slowly (user exited with error)
        mock_manager.run_interactive.return_value = (1, 30.0)
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["claude"])

        mock_manager.exec_interactive.assert_not_called()
        assert result.exit_code == 1

    def test_claude_safe_mode(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["claude", "--safe"])

        mock_manager.exec_interactive.assert_called_once()
        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert cmd == ["claude"]
        assert mock_manager.exec_interactive.call_args[1]["extra_env"] == TEST_EXEC_ENV
        # Should NOT use run_interactive at all
        mock_manager.run_interactive.assert_not_called()

    def test_claude_with_extra_args(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["claude", "--", "--debug"])

        cmd = mock_manager.run_interactive.call_args[0][1]
        assert cmd == ["claude", "--dangerously-skip-permissions", "-c", "--debug"]

    def test_claude_remote_flag(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["claude", "--remote"])

        cmd = mock_manager.run_interactive.call_args[0][1]
        assert cmd == ["claude", "--dangerously-skip-permissions", "--remote", "-c"]
        assert "(remote)" in result.output

    def test_claude_remote_with_name(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["claude", "--remote", "--name", "my-session"])

        cmd = mock_manager.run_interactive.call_args[0][1]
        assert cmd == [
            "claude",
            "--dangerously-skip-permissions",
            "--remote",
            "--name",
            "my-session",
            "-c",
        ]
        assert "(remote)" in result.output

    def test_claude_remote_with_name_retry(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (1, 1.0)
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["claude", "--remote", "--name", "my-session"])

        cmd_fresh = mock_manager.exec_interactive.call_args[0][1]
        assert cmd_fresh == [
            "claude",
            "--dangerously-skip-permissions",
            "--remote",
            "--name",
            "my-session",
        ]

    def test_claude_remote_safe_mode(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["claude", "--safe", "--remote", "--name", "my-session"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert cmd == ["claude", "--remote", "--name", "my-session"]
        assert "(safe mode)" in result.output
        assert "(remote)" in result.output

    def test_claude_name_without_remote_errors(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        result = self.runner.invoke(cli, ["claude", "--name", "my-session"])

        assert result.exit_code != 0
        assert "--name requires --remote" in result.output

    def test_codex_command(self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock):
        config = MagicMock()
        config.codex_openai_api_key = ""
        config.codex_provider = ""
        config.codex_profile = ""
        config.bedrock_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = "/tmp/test"
        mock_config.return_value = config

        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["codex"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert "codex" in cmd
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd
        assert mock_manager.exec_interactive.call_args[1]["extra_env"] == TEST_EXEC_ENV

    def test_codex_safe_mode(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        config = MagicMock()
        config.codex_openai_api_key = ""
        config.codex_provider = ""
        config.codex_profile = ""
        config.bedrock_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = "/tmp/test"
        mock_config.return_value = config

        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["codex", "--safe"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert "--dangerously-bypass-approvals-and-sandbox" not in cmd

    @patch("ai_shell.cli.commands.tools._inject_codex_api_key")
    def test_codex_openai_api_key_from_config(
        self, mock_inject, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        config = MagicMock()
        config.codex_openai_api_key = "sk-test-123"
        config.codex_provider = ""
        config.codex_profile = ""
        config.bedrock_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = "/tmp/test"
        mock_config.return_value = config

        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["codex"])

        # Verify auth.json was patched with the configured key
        mock_inject.assert_called_once_with("augint-shell-test-dev", "sk-test-123")

    @patch("ai_shell.cli.commands.tools._inject_codex_api_key")
    def test_codex_bedrock_launch_message(
        self, mock_inject, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        config = MagicMock()
        config.codex_openai_api_key = ""
        config.codex_provider = ""
        config.codex_profile = ""
        config.bedrock_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = "/tmp/test"
        mock_config.return_value = config

        bedrock_env = dict(TEST_EXEC_ENV)
        bedrock_env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        bedrock_env["AWS_PROFILE"] = "rd"
        mock_build_env.return_value = bedrock_env
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["codex", "--aws"])

        assert "Bedrock" in result.output
        assert "profile=rd" in result.output
        assert "region=us-east-1" in result.output

    def test_codex_config_provider_activates_bedrock(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        config = MagicMock()
        config.codex_provider = "aws"
        config.codex_openai_api_key = ""
        config.codex_profile = "rd"
        config.bedrock_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = "/tmp/test"
        mock_config.return_value = config

        bedrock_env = dict(TEST_EXEC_ENV)
        bedrock_env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        bedrock_env["AWS_PROFILE"] = "rd"
        mock_build_env.return_value = bedrock_env
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["codex"])

        assert "Bedrock" in result.output
        mock_build_env.assert_called_once()
        call_kwargs = mock_build_env.call_args[1]
        assert call_kwargs["bedrock"] is True

    @patch("ai_shell.cli.commands.tools._inject_codex_api_key")
    def test_codex_bedrock_preflight_called(
        self, mock_inject, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        config = MagicMock()
        config.codex_openai_api_key = ""
        config.codex_provider = ""
        config.codex_profile = ""
        config.bedrock_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = "/tmp/test"
        mock_config.return_value = config

        bedrock_env = dict(TEST_EXEC_ENV)
        bedrock_env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        bedrock_env["AWS_PROFILE"] = "rd"
        mock_build_env.return_value = bedrock_env
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["codex", "--aws"])

        mock_check_bedrock.assert_called_once()

    @patch("ai_shell.cli.commands.tools._inject_codex_api_key")
    def test_codex_bedrock_no_preflight_skips_check(
        self, mock_inject, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        config = MagicMock()
        config.codex_openai_api_key = ""
        config.codex_provider = ""
        config.codex_profile = ""
        config.bedrock_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = "/tmp/test"
        mock_config.return_value = config

        bedrock_env = dict(TEST_EXEC_ENV)
        bedrock_env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        bedrock_env["AWS_PROFILE"] = "rd"
        mock_build_env.return_value = bedrock_env
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["codex", "--aws", "--no-preflight"])

        mock_check_bedrock.assert_not_called()

    def test_shell_command(self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["shell"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert cmd == ["/bin/bash"]
        assert mock_manager.exec_interactive.call_args[1]["extra_env"] == TEST_EXEC_ENV

    @patch("ai_shell.scaffold.scaffold_aider")
    def test_aider_passes_model_and_env(
        self, mock_scaffold_aider, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        config = MagicMock()
        config.aider_model = "ollama_chat/qwen3-coder-next"
        config.ollama_port = 11434
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
        assert "ollama_chat/qwen3-coder-next" in cmd
        assert "--yes-always" in cmd
        assert extra_env["OLLAMA_API_BASE"] == "http://host.docker.internal:11434"
        assert extra_env["GH_TOKEN"] == "test-token"

    @patch("ai_shell.scaffold.scaffold_aider")
    def test_aider_safe_mode(
        self, mock_scaffold_aider, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        config = MagicMock()
        config.aider_model = "ollama_chat/qwen3-coder-next"
        mock_config.return_value = config

        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.config = config
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["aider", "--safe"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert "--yes-always" not in cmd
        assert "--model" in cmd
        assert "--restore-chat-history" in cmd

    def test_opencode_init_calls_scaffold(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with (
                patch("ai_shell.scaffold.scaffold_opencode") as mock_scaffold,
                patch("ai_shell.notes_merge.merge_notes_into_context") as mock_merge,
            ):
                result = self.runner.invoke(cli, ["opencode", "--init"])

        mock_scaffold.assert_called_once_with(
            "/tmp/test",
            overwrite=False,
            clean=False,
            merge=False,
            repo_type=None,
            branch_strategy=None,
        )
        mock_manager_cls.assert_not_called()
        mock_merge.assert_called_once_with("/tmp/test", "opencode", background=True)
        assert result.exit_code == 0

    def test_opencode_update_calls_scaffold_with_merge(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with (
                patch("ai_shell.scaffold.scaffold_opencode") as mock_scaffold,
                patch("ai_shell.notes_merge.merge_notes_into_context"),
            ):
                result = self.runner.invoke(cli, ["opencode", "--update"])

        mock_scaffold.assert_called_once_with(
            "/tmp/test",
            overwrite=False,
            clean=False,
            merge=True,
            repo_type=None,
            branch_strategy=None,
        )
        assert result.exit_code == 0

    def test_opencode_reset_calls_scaffold_with_overwrite(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with (
                patch("ai_shell.scaffold.scaffold_opencode") as mock_scaffold,
                patch("ai_shell.notes_merge.merge_notes_into_context"),
            ):
                result = self.runner.invoke(cli, ["opencode", "--reset"])

        mock_scaffold.assert_called_once_with(
            "/tmp/test",
            overwrite=True,
            clean=False,
            merge=False,
            repo_type=None,
            branch_strategy=None,
        )
        assert result.exit_code == 0

    def test_opencode_clean_calls_scaffold_with_clean(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with patch("ai_shell.scaffold.scaffold_opencode") as mock_scaffold:
                result = self.runner.invoke(cli, ["opencode", "--clean"])

        mock_scaffold.assert_called_once_with(
            "/tmp/test",
            overwrite=True,
            clean=True,
            merge=False,
            repo_type=None,
            branch_strategy=None,
        )
        mock_manager_cls.assert_not_called()
        assert result.exit_code == 0

    def test_codex_init_calls_scaffold(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with (
                patch("ai_shell.scaffold.scaffold_codex") as mock_scaffold,
                patch("ai_shell.notes_merge.merge_notes_into_context") as mock_merge,
            ):
                result = self.runner.invoke(cli, ["codex", "--init"])

        mock_scaffold.assert_called_once_with(
            "/tmp/test",
            overwrite=False,
            clean=False,
            merge=False,
            repo_type=None,
            branch_strategy=None,
        )
        mock_manager_cls.assert_not_called()
        mock_merge.assert_called_once_with("/tmp/test", "codex", background=True)
        assert result.exit_code == 0

    def test_codex_update_calls_scaffold_with_merge(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with (
                patch("ai_shell.scaffold.scaffold_codex") as mock_scaffold,
                patch("ai_shell.notes_merge.merge_notes_into_context"),
            ):
                result = self.runner.invoke(cli, ["codex", "--update"])

        mock_scaffold.assert_called_once_with(
            "/tmp/test",
            overwrite=False,
            clean=False,
            merge=True,
            repo_type=None,
            branch_strategy=None,
        )
        assert result.exit_code == 0

    def test_codex_reset_calls_scaffold_with_overwrite(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with (
                patch("ai_shell.scaffold.scaffold_codex") as mock_scaffold,
                patch("ai_shell.notes_merge.merge_notes_into_context"),
            ):
                result = self.runner.invoke(cli, ["codex", "--reset"])

        mock_scaffold.assert_called_once_with(
            "/tmp/test",
            overwrite=True,
            clean=False,
            merge=False,
            repo_type=None,
            branch_strategy=None,
        )
        assert result.exit_code == 0

    def test_codex_clean_calls_scaffold_with_clean(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with patch("ai_shell.scaffold.scaffold_codex") as mock_scaffold:
                result = self.runner.invoke(cli, ["codex", "--clean"])

        mock_scaffold.assert_called_once_with(
            "/tmp/test",
            overwrite=True,
            clean=True,
            merge=False,
            repo_type=None,
            branch_strategy=None,
        )
        mock_manager_cls.assert_not_called()
        assert result.exit_code == 0

    def test_aider_init_calls_scaffold(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with patch("ai_shell.scaffold.scaffold_aider") as mock_scaffold:
                result = self.runner.invoke(cli, ["aider", "--init"])

        mock_scaffold.assert_called_once_with(
            "/tmp/test",
            overwrite=False,
            clean=False,
            merge=False,
            repo_type=None,
        )
        mock_manager_cls.assert_not_called()
        assert result.exit_code == 0

    def test_aider_update_calls_scaffold_with_merge(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with patch("ai_shell.scaffold.scaffold_aider") as mock_scaffold:
                result = self.runner.invoke(cli, ["aider", "--update"])

        mock_scaffold.assert_called_once_with(
            "/tmp/test",
            overwrite=False,
            clean=False,
            merge=True,
            repo_type=None,
        )
        assert result.exit_code == 0

    def test_aider_reset_calls_scaffold_with_overwrite(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with patch("ai_shell.scaffold.scaffold_aider") as mock_scaffold:
                result = self.runner.invoke(cli, ["aider", "--reset"])

        mock_scaffold.assert_called_once_with(
            "/tmp/test",
            overwrite=True,
            clean=False,
            merge=False,
            repo_type=None,
        )
        assert result.exit_code == 0

    def test_aider_clean_calls_scaffold_with_clean(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with patch("ai_shell.scaffold.scaffold_aider") as mock_scaffold:
                result = self.runner.invoke(cli, ["aider", "--clean"])

        mock_scaffold.assert_called_once_with(
            "/tmp/test",
            overwrite=True,
            clean=True,
            merge=False,
            repo_type=None,
        )
        mock_manager_cls.assert_not_called()
        assert result.exit_code == 0

    def test_claude_update_calls_merge(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with (
                patch("ai_shell.scaffold.scaffold_claude"),
                patch("ai_shell.notes_merge.merge_notes_into_context") as mock_merge,
            ):
                result = self.runner.invoke(cli, ["claude", "--update"])

        mock_merge.assert_called_once_with("/tmp/test", "claude", background=True)
        assert result.exit_code == 0

    def test_claude_update_with_no_merge_skips_merge(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with (
                patch("ai_shell.scaffold.scaffold_claude"),
                patch("ai_shell.notes_merge.merge_notes_into_context") as mock_merge,
            ):
                result = self.runner.invoke(cli, ["claude", "--update", "--no-merge"])

        mock_merge.assert_not_called()
        assert result.exit_code == 0

    def test_claude_init_calls_merge(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with (
                patch("ai_shell.scaffold.scaffold_claude"),
                patch("ai_shell.notes_merge.merge_notes_into_context") as mock_merge,
            ):
                self.runner.invoke(cli, ["claude", "--init"])

        mock_merge.assert_called_once_with("/tmp/test", "claude", background=True)

    def test_claude_clean_does_not_call_merge(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with (
                patch("ai_shell.scaffold.scaffold_claude"),
                patch("ai_shell.notes_merge.merge_notes_into_context") as mock_merge,
            ):
                self.runner.invoke(cli, ["claude", "--clean"])

        mock_merge.assert_not_called()

    def test_codex_update_calls_merge(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with (
                patch("ai_shell.scaffold.scaffold_codex"),
                patch("ai_shell.notes_merge.merge_notes_into_context") as mock_merge,
            ):
                result = self.runner.invoke(cli, ["codex", "--update"])

        mock_merge.assert_called_once_with("/tmp/test", "codex", background=True)
        assert result.exit_code == 0

    def test_codex_update_with_no_merge_skips_merge(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with (
                patch("ai_shell.scaffold.scaffold_codex"),
                patch("ai_shell.notes_merge.merge_notes_into_context") as mock_merge,
            ):
                result = self.runner.invoke(cli, ["codex", "--update", "--no-merge"])

        mock_merge.assert_not_called()
        assert result.exit_code == 0

    def test_opencode_update_calls_merge(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with (
                patch("ai_shell.scaffold.scaffold_opencode"),
                patch("ai_shell.notes_merge.merge_notes_into_context") as mock_merge,
            ):
                result = self.runner.invoke(cli, ["opencode", "--update"])

        mock_merge.assert_called_once_with("/tmp/test", "opencode", background=True)
        assert result.exit_code == 0

    def test_opencode_update_with_no_merge_skips_merge(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with (
                patch("ai_shell.scaffold.scaffold_opencode"),
                patch("ai_shell.notes_merge.merge_notes_into_context") as mock_merge,
            ):
                result = self.runner.invoke(cli, ["opencode", "--update", "--no-merge"])

        mock_merge.assert_not_called()
        assert result.exit_code == 0

    def test_init_update_all_with_no_merge_skips_merge(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with (
                patch("ai_shell.scaffold.scaffold_project"),
                patch("ai_shell.scaffold.scaffold_claude"),
                patch("ai_shell.scaffold.scaffold_opencode"),
                patch("ai_shell.scaffold.scaffold_codex"),
                patch("ai_shell.scaffold.scaffold_aider"),
                patch("ai_shell.notes_merge.merge_notes_into_context") as mock_merge,
            ):
                result = self.runner.invoke(
                    cli,
                    ["init", "--update", "--all", "--no-merge", "--lib"],
                )

        mock_merge.assert_not_called()
        assert result.exit_code == 0

    def test_claude_bedrock_launch_message(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        bedrock_env = dict(TEST_EXEC_ENV)
        bedrock_env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        bedrock_env["AWS_PROFILE"] = "rd"
        mock_build_env.return_value = bedrock_env
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["claude", "--aws"])

        assert "Bedrock" in result.output
        assert "profile=rd" in result.output
        assert "region=us-east-1" in result.output

    def test_claude_config_provider_activates_bedrock(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        config = MagicMock()
        config.claude_provider = "aws"
        config.bedrock_profile = "rd"
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = "/tmp/test"
        mock_config.return_value = config

        bedrock_env = dict(TEST_EXEC_ENV)
        bedrock_env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        bedrock_env["AWS_PROFILE"] = "rd"
        mock_build_env.return_value = bedrock_env
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["claude"])

        assert "Bedrock" in result.output
        mock_build_env.assert_called_once()
        call_kwargs = mock_build_env.call_args[1]
        assert call_kwargs["bedrock"] is True

    def test_claude_bedrock_preflight_called(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        bedrock_env = dict(TEST_EXEC_ENV)
        bedrock_env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        bedrock_env["AWS_PROFILE"] = "rd"
        mock_build_env.return_value = bedrock_env
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["claude", "--aws"])

        mock_check_bedrock.assert_called_once_with("augint-shell-test-dev", bedrock_env)

    def test_claude_bedrock_preflight_failure_blocks_launch(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        bedrock_env = dict(TEST_EXEC_ENV)
        bedrock_env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        bedrock_env["AWS_PROFILE"] = "rd"
        mock_build_env.return_value = bedrock_env
        mock_check_bedrock.side_effect = click.ClickException("Bedrock access check failed")
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["claude", "--aws"])

        assert result.exit_code != 0
        assert "Bedrock access check failed" in result.output
        mock_manager.run_interactive.assert_not_called()
        mock_manager.exec_interactive.assert_not_called()

    def test_claude_no_bedrock_skips_preflight(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["claude"])

        mock_check_bedrock.assert_not_called()

    def test_version_flag(self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock):
        result = self.runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "ai-shell" in result.output


class TestCheckBedrockAccess:
    @patch("ai_shell.cli.commands.tools.subprocess.run")
    def test_passes_on_success(self, mock_run):
        from ai_shell.cli.commands.tools import _check_bedrock_access

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        exec_env = {"AWS_PROFILE": "rd", "AWS_REGION": "us-east-1"}

        _check_bedrock_access("test-container", exec_env)

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "docker" in args
        assert "test-container" in args
        assert "bash" in args
        # Shell command contains invoke-model and profile
        shell_cmd = args[-1]
        assert "invoke-model" in shell_cmd
        assert "--profile rd" in shell_cmd

    @patch("ai_shell.cli.commands.tools.subprocess.run")
    def test_raises_on_failure(self, mock_run):
        from ai_shell.cli.commands.tools import _check_bedrock_access

        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="AccessDeniedException: not authorized to perform bedrock:InvokeModel",
        )
        exec_env = {"AWS_PROFILE": "rd", "AWS_REGION": "us-east-1"}

        with pytest.raises(click.ClickException, match="Bedrock access check failed"):
            _check_bedrock_access("test-container", exec_env)

    @patch("ai_shell.cli.commands.tools.subprocess.run")
    def test_no_profile_flag_when_empty(self, mock_run):
        from ai_shell.cli.commands.tools import _check_bedrock_access

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        exec_env = {"AWS_PROFILE": "", "AWS_REGION": "us-east-1"}

        _check_bedrock_access("test-container", exec_env)

        args = mock_run.call_args[0][0]
        shell_cmd = args[-1]
        assert "--profile" not in shell_cmd


class TestAutoInit:
    """Auto-init triggers scaffold on first run when config files are missing."""

    def setup_method(self):
        self.runner = CliRunner()

    @patch("ai_shell.cli.commands.tools._check_bedrock_access")
    @patch("ai_shell.cli.commands.tools.build_dev_environment")
    @patch("ai_shell.cli.commands.tools.ContainerManager")
    @patch("ai_shell.cli.commands.tools.load_config")
    @patch("ai_shell.scaffold.scaffold_opencode")
    def test_opencode_auto_inits_when_config_missing(
        self, mock_scaffold, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = {}
        config = MagicMock()
        config.opencode_provider = ""
        mock_config.return_value = config
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        with self.runner.isolated_filesystem():
            self.runner.invoke(cli, ["opencode"])

        mock_scaffold.assert_called_once()

    @patch("ai_shell.cli.commands.tools._check_bedrock_access")
    @patch("ai_shell.cli.commands.tools.build_dev_environment")
    @patch("ai_shell.cli.commands.tools.ContainerManager")
    @patch("ai_shell.cli.commands.tools.load_config")
    @patch("ai_shell.scaffold.scaffold_claude")
    def test_claude_auto_inits_when_config_missing(
        self, mock_scaffold, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = {}
        config = MagicMock()
        config.claude_provider = ""
        mock_config.return_value = config
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        with self.runner.isolated_filesystem():
            self.runner.invoke(cli, ["claude"])

        mock_scaffold.assert_called_once()

    @patch("ai_shell.cli.commands.tools._check_bedrock_access")
    @patch("ai_shell.cli.commands.tools.build_dev_environment")
    @patch("ai_shell.cli.commands.tools.ContainerManager")
    @patch("ai_shell.cli.commands.tools.load_config")
    @patch("ai_shell.scaffold.scaffold_codex")
    def test_codex_auto_inits_when_config_missing(
        self, mock_scaffold, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = {}
        mock_config.return_value = MagicMock()
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        with self.runner.isolated_filesystem():
            self.runner.invoke(cli, ["codex"])

        mock_scaffold.assert_called_once()

    @patch("ai_shell.cli.commands.tools._check_bedrock_access")
    @patch("ai_shell.cli.commands.tools.build_dev_environment")
    @patch("ai_shell.cli.commands.tools.ContainerManager")
    @patch("ai_shell.cli.commands.tools.load_config")
    @patch("ai_shell.scaffold.scaffold_aider")
    def test_aider_auto_inits_when_config_missing(
        self, mock_scaffold, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = {}
        config = MagicMock()
        config.aider_model = "ollama_chat/qwen3-coder-next"
        config.ollama_port = 11434
        mock_config.return_value = config
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        with self.runner.isolated_filesystem():
            self.runner.invoke(cli, ["aider"])

        mock_scaffold.assert_called_once()
