"""Tests for CLI tool subcommands."""

from pathlib import Path
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

    @patch("ai_shell.cli.commands.tools._setup_worktree")
    def test_claude_worktree_named(
        self, mock_setup_wt, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        """--worktree <name> creates the worktree and passes workdir to exec calls."""
        config = MagicMock()
        config.project_name = "my-project"
        config.claude_provider = ""
        config.bedrock_profile = ""
        config.openai_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        mock_config.return_value = config

        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        wt_abs = "/root/projects/my-project/.claude/worktrees/feat-123"
        mock_setup_wt.return_value = wt_abs

        self.runner.invoke(cli, ["claude", "--worktree", "feat-123"])

        mock_setup_wt.assert_called_once_with(
            "augint-shell-test-dev",
            "/root/projects/my-project",
            "feat-123",
        )
        call_kwargs = mock_manager.run_interactive.call_args[1]
        assert call_kwargs["workdir"] == wt_abs

    @patch("ai_shell.cli.commands.tools._setup_worktree")
    @patch("ai_shell.cli.commands.tools._generate_worktree_name")
    def test_claude_worktree_auto_named(
        self,
        mock_gen_name,
        mock_setup_wt,
        mock_config,
        mock_manager_cls,
        mock_build_env,
        mock_check_bedrock,
    ):
        """--worktree without a value auto-generates a name."""
        config = MagicMock()
        config.project_name = "my-project"
        config.claude_provider = ""
        config.bedrock_profile = ""
        config.openai_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        mock_config.return_value = config

        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        mock_gen_name.return_value = "abc12345"
        wt_abs = "/root/projects/my-project/.claude/worktrees/abc12345"
        mock_setup_wt.return_value = wt_abs

        self.runner.invoke(cli, ["claude", "-w"])

        mock_gen_name.assert_called_once()
        mock_setup_wt.assert_called_once_with(
            "augint-shell-test-dev",
            "/root/projects/my-project",
            "abc12345",
        )
        call_kwargs = mock_manager.run_interactive.call_args[1]
        assert call_kwargs["workdir"] == wt_abs

    @patch("ai_shell.cli.commands.tools._setup_worktree")
    def test_claude_worktree_safe_mode(
        self, mock_setup_wt, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        """--worktree with --safe passes workdir to exec_interactive."""
        config = MagicMock()
        config.project_name = "my-project"
        config.claude_provider = ""
        config.bedrock_profile = ""
        config.openai_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        mock_config.return_value = config

        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        wt_abs = "/root/projects/my-project/.claude/worktrees/feat-safe"
        mock_setup_wt.return_value = wt_abs

        self.runner.invoke(cli, ["claude", "--worktree", "feat-safe", "--safe"])

        call_kwargs = mock_manager.exec_interactive.call_args[1]
        assert call_kwargs["workdir"] == wt_abs

    def test_claude_no_worktree_passes_none_workdir(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        """When --worktree is not given, workdir=None is passed (no -w flag on docker exec)."""
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["claude"])

        mock_manager.ensure_dev_container.assert_called_once()
        mock_manager.run_interactive.assert_called_once()
        cmd = mock_manager.run_interactive.call_args[0][1]
        assert cmd == ["claude", "--dangerously-skip-permissions", "-c"]
        call_kwargs = mock_manager.run_interactive.call_args[1]
        assert call_kwargs["workdir"] is None
        assert result.exit_code == 0

        config = MagicMock()
        config.bedrock_profile = ""
        config.openai_profile = ""
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
        config.bedrock_profile = ""
        config.openai_profile = ""
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

    def test_codex_bedrock_launch_message(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        config = MagicMock()
        config.bedrock_profile = ""
        config.openai_profile = ""
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

    def test_codex_aws_uses_bedrock_profile_from_config(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        config = MagicMock()
        config.bedrock_profile = "rd"
        config.openai_profile = ""
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
        mock_build_env.assert_called_once()
        call_kwargs = mock_build_env.call_args[1]
        assert call_kwargs["bedrock"] is True
        assert call_kwargs["bedrock_profile"] == "rd"

    def test_codex_openai_profile_flag_passed_to_build_env(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        config = MagicMock()
        config.bedrock_profile = ""
        config.openai_profile = ""
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

        self.runner.invoke(cli, ["codex", "--openai-profile", "aillc"])

        mock_build_env.assert_called_once()
        call_kwargs = mock_build_env.call_args[1]
        assert call_kwargs["openai_profile"] == "aillc"

    def test_codex_openai_profile_from_config(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        config = MagicMock()
        config.bedrock_profile = ""
        config.openai_profile = "personal"
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

        mock_build_env.assert_called_once()
        call_kwargs = mock_build_env.call_args[1]
        assert call_kwargs["openai_profile"] == "personal"

    def test_codex_bedrock_preflight_called(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        config = MagicMock()
        config.bedrock_profile = ""
        config.openai_profile = ""
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

    def test_shell_bash(self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["shell", "bash"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert cmd == ["/bin/bash", "-l"]
        assert mock_manager.exec_interactive.call_args[1]["extra_env"] == TEST_EXEC_ENV

    def test_shell_zsh(self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["shell", "zsh"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert cmd == ["/usr/bin/zsh", "-l"]

    def test_shell_fish(self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["shell", "fish"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert cmd == ["/usr/bin/fish", "-l"]

    def test_shell_defaults_to_bash_when_no_arg(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["shell"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert cmd == ["/bin/bash", "-l"]

    def test_shell_rejects_invalid(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        result = self.runner.invoke(cli, ["shell", "csh"])
        assert result.exit_code != 0

    def test_aider_passes_model_and_env(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        config = MagicMock()
        config.primary_coding_model = "qwen3-coder:30b-a3b-q4_K_M"
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
        assert "ollama_chat/qwen3-coder:30b-a3b-q4_K_M" in cmd
        assert "--yes-always" in cmd
        assert extra_env["OLLAMA_API_BASE"] == "http://host.docker.internal:11434"
        assert extra_env["GH_TOKEN"] == "test-token"

    def test_aider_safe_mode(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        config = MagicMock()
        config.primary_coding_model = "qwen3-coder:30b-a3b-q4_K_M"
        config.ollama_port = 11434
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

    @patch("ai_shell.cli.commands.tools._ensure_pi_ollama_provider")
    @patch("ai_shell.cli.commands.tools._check_ollama_running")
    def test_pi_default_uses_ollama_model(
        self,
        mock_check_ollama,
        mock_ensure_ollama,
        mock_config,
        mock_manager_cls,
        mock_build_env,
        mock_check_bedrock,
    ):
        mock_check_ollama.return_value = None
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        config = MagicMock()
        config.primary_coding_model = "qwen3-coder:30b-a3b-q4_K_M"
        config.bedrock_profile = ""
        config.openai_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = "/tmp/test"
        mock_config.return_value = config

        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["pi"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert cmd == ["pi"]
        mock_check_ollama.assert_called_once()
        mock_ensure_ollama.assert_called_once_with(config)

    @patch("ai_shell.cli.commands.tools._ensure_pi_ollama_provider")
    @patch("ai_shell.cli.commands.tools._check_ollama_running")
    def test_pi_bedrock_skips_ollama_check(
        self,
        mock_check_ollama,
        mock_ensure_ollama,
        mock_config,
        mock_manager_cls,
        mock_build_env,
        mock_check_bedrock,
    ):
        bedrock_env = dict(TEST_EXEC_ENV)
        bedrock_env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        bedrock_env["AWS_PROFILE"] = "rd"
        mock_build_env.return_value = bedrock_env
        config = MagicMock()
        config.primary_coding_model = "qwen3-coder:30b-a3b-q4_K_M"
        config.bedrock_profile = ""
        config.bedrock_model = "us.meta.llama3-3-70b-instruct-v1:0"
        config.openai_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = "/tmp/test"
        mock_config.return_value = config

        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["pi", "--aws"])

        mock_check_ollama.assert_not_called()
        mock_ensure_ollama.assert_called_once_with(config)
        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert cmd == [
            "pi",
            "--provider",
            "amazon-bedrock",
            "--model",
            "us.meta.llama3-3-70b-instruct-v1:0",
        ]

    @patch("ai_shell.cli.commands.tools._ensure_pi_ollama_provider")
    @patch("ai_shell.cli.commands.tools._check_ollama_running")
    def test_pi_doom_flag(
        self,
        mock_check_ollama,
        mock_ensure_ollama,
        mock_config,
        mock_manager_cls,
        mock_build_env,
        mock_check_bedrock,
    ):
        mock_check_ollama.return_value = None
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        config = MagicMock()
        config.primary_coding_model = "qwen3-coder:30b-a3b-q4_K_M"
        config.bedrock_profile = ""
        config.openai_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = "/tmp/test"
        mock_config.return_value = config

        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["pi", "--doom"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert cmd == ["pi", "-e", "npm:pi-doom"]
        assert "DOOM" in result.output

    @patch("ai_shell.cli.commands.tools._inject_mcp_config")
    @patch("ai_shell.local_chrome.start_chrome_proxy")
    @patch("ai_shell.local_chrome.ensure_host_chrome", return_value=9222)
    def test_claude_local_chrome_injects_mcp_config(
        self,
        mock_ensure,
        mock_proxy,
        mock_inject_mcp,
        mock_config,
        mock_manager_cls,
        mock_build_env,
        mock_check_bedrock,
    ):
        """--local-chrome ensures Chrome, injects MCP config, adds --mcp-config to cmd."""
        config = MagicMock()
        config.claude_provider = ""
        config.bedrock_profile = ""
        config.openai_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_name = "test-project"
        config.project_dir = Path("/tmp/test-project")
        config.local_chrome = False
        mock_config.return_value = config

        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        with patch("ai_shell.local_chrome.write_mcp_config") as mock_write:
            mock_write.return_value = Path("/tmp/chrome-mcp.json")
            result = self.runner.invoke(cli, ["claude", "--local-chrome"])

        assert result.exit_code == 0
        cmd = mock_manager.run_interactive.call_args[0][1]
        assert "--mcp-config" in cmd
        assert "/etc/ai-shell/chrome-mcp.json" in cmd
        mock_inject_mcp.assert_called_once()
        mock_ensure.assert_called_once_with(
            "augint-shell-test-dev",
            project_name="test-project",
            project_dir=Path("/tmp/test-project"),
        )
        mock_proxy.assert_called_once_with("augint-shell-test-dev", 9222)

    @patch("ai_shell.cli.commands.tools._inject_mcp_config")
    @patch("ai_shell.local_chrome.start_chrome_proxy")
    @patch("ai_shell.local_chrome.ensure_host_chrome", return_value=54321)
    def test_claude_local_chrome_retry_includes_mcp_config(
        self,
        mock_ensure,
        mock_proxy,
        mock_inject_mcp,
        mock_config,
        mock_manager_cls,
        mock_build_env,
        mock_check_bedrock,
    ):
        """--local-chrome injects --mcp-config in both retry attempts."""
        config = MagicMock()
        config.claude_provider = ""
        config.bedrock_profile = ""
        config.openai_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_name = "test-project"
        config.project_dir = Path("/tmp/test-project")
        config.local_chrome = False
        mock_config.return_value = config

        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (1, 1.0)  # Fast failure
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        with patch("ai_shell.local_chrome.write_mcp_config") as mock_write:
            mock_write.return_value = Path("/tmp/chrome-mcp.json")
            self.runner.invoke(cli, ["claude", "--local-chrome"])

        # First attempt (with -c)
        cmd_continue = mock_manager.run_interactive.call_args[0][1]
        assert "--mcp-config" in cmd_continue
        # Retry attempt (without -c)
        cmd_fresh = mock_manager.exec_interactive.call_args[0][1]
        assert "--mcp-config" in cmd_fresh
        mock_ensure.assert_called_once_with(
            "augint-shell-test-dev",
            project_name="test-project",
            project_dir=Path("/tmp/test-project"),
        )

    @patch("ai_shell.local_chrome.ensure_host_chrome")
    def test_claude_local_chrome_fails_fast_when_unreachable(
        self, mock_ensure, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        """--local-chrome fails with instructions when Chrome can't be started."""
        from ai_shell.local_chrome import LocalChromeUnavailable

        mock_ensure.side_effect = LocalChromeUnavailable("could not be found")
        config = MagicMock()
        config.claude_provider = ""
        config.bedrock_profile = ""
        config.openai_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_name = "test-project"
        config.project_dir = Path("/tmp/test-project")
        config.local_chrome = False
        mock_config.return_value = config

        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["claude", "--local-chrome"])

        assert result.exit_code != 0
        assert "could not be found" in result.output
        mock_manager.run_interactive.assert_not_called()
        mock_manager.exec_interactive.assert_not_called()
        mock_ensure.assert_called_once_with(
            "augint-shell-test-dev",
            project_name="test-project",
            project_dir=Path("/tmp/test-project"),
        )

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
        config.openai_profile = ""
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

    def test_opencode_web_mode(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        config = MagicMock()
        config.bedrock_profile = ""
        config.openai_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = Path("/tmp/test")
        config.project_name = "test"
        config.primary_coding_model = "qwen3-coder:30b-a3b-q4_K_M"
        mock_config.return_value = config

        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["opencode", "--web"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert "web" in cmd
        assert "--hostname" in cmd
        assert "0.0.0.0" in cmd
        assert "--port" in cmd
        assert "4096" in cmd
        assert "http://localhost:" in result.output

    def test_opencode_web_custom_port(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        config = MagicMock()
        config.bedrock_profile = ""
        config.openai_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = Path("/tmp/test")
        config.project_name = "test"
        config.primary_coding_model = "qwen3-coder:30b-a3b-q4_K_M"
        mock_config.return_value = config

        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["opencode", "--web", "--port", "8080"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert "--port" in cmd
        assert "8080" in cmd

    def test_opencode_tui_default(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        config = MagicMock()
        config.bedrock_profile = ""
        config.openai_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = Path("/tmp/test")
        config.project_name = "test"
        config.primary_coding_model = "qwen3-coder:30b-a3b-q4_K_M"
        mock_config.return_value = config

        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["opencode"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert "web" not in cmd
        assert "--hostname" not in cmd

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
        shell_cmd = args[-1]
        assert "converse" in shell_cmd
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


class TestHelpShortFlag:
    """Verify -h works as alias for --help across all groups and commands."""

    def setup_method(self):
        self.runner = CliRunner()

    def test_main_group_h_flag(self):
        result = self.runner.invoke(cli, ["-h"])
        assert result.exit_code == 0
        assert "Usage" in result.output

    def test_claude_h_flag(self):
        result = self.runner.invoke(cli, ["claude", "-h"])
        assert result.exit_code == 0
        assert "Usage" in result.output

    def test_llm_h_flag(self):
        result = self.runner.invoke(cli, ["llm", "-h"])
        assert result.exit_code == 0
        assert "Usage" in result.output

    def test_manage_h_flag(self):
        result = self.runner.invoke(cli, ["manage", "-h"])
        assert result.exit_code == 0
        assert "Usage" in result.output
