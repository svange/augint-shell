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

    @patch("ai_shell.t3.attach")
    def test_t3_flag_attaches_before_shell_launch(
        self, mock_attach, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["shell", "--t3"])

        mock_attach.assert_called_once()
        assert mock_attach.call_args[0][1] == "augint-shell-test-dev"
        assert mock_attach.call_args[0][3] == TEST_EXEC_ENV

    @patch("ai_shell.t3.attach")
    def test_no_t3_flag_leaves_t3_alone(
        self, mock_attach, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["shell"])

        mock_attach.assert_not_called()

    @patch("ai_shell.t3.attach")
    def test_t3_flag_attaches_before_claude_launch(
        self, mock_attach, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["claude", "--t3"])

        mock_attach.assert_called_once()
        mock_manager.run_interactive.assert_called_once()

    @patch("ai_shell.t3.attach")
    def test_t3_failure_aborts_launch(
        self, mock_attach, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        from ai_shell.t3 import T3Error

        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager_cls.return_value = mock_manager
        mock_attach.side_effect = T3Error("server never came up")

        result = self.runner.invoke(cli, ["claude", "--t3"])

        assert result.exit_code != 0
        assert "server never came up" in result.output
        mock_manager.run_interactive.assert_not_called()

    @patch("ai_shell.t3.attach")
    def test_t3_flag_attaches_before_codex_launch(
        self, mock_attach, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["codex", "--t3"])

        mock_attach.assert_called_once()

    @patch("ai_shell.t3.attach")
    def test_t3_flag_attaches_before_opencode_launch(
        self, mock_attach, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        from ai_shell.config import AiShellConfig

        mock_config.return_value = AiShellConfig(project_name="demo", project_dir=Path("/tmp/demo"))
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-demo-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["opencode", "--t3"])

        mock_attach.assert_called_once()

    @patch("ai_shell.expo.attach")
    def test_expo_flag_attaches_before_claude_launch(
        self, mock_attach, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["claude", "--expo"])

        mock_attach.assert_called_once()
        assert mock_attach.call_args.kwargs["explicit"] is True

    @patch("ai_shell.expo.attach")
    def test_expo_auto_detection_runs_without_the_flag(
        self, mock_attach, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["claude"])

        mock_attach.assert_called_once()
        assert mock_attach.call_args.kwargs["explicit"] is False

    @patch("ai_shell.expo.attach")
    def test_expo_auto_disabled_in_config_skips_detection(
        self, mock_attach, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        from ai_shell.config import AiShellConfig

        mock_config.return_value = AiShellConfig(
            project_name="demo", project_dir=Path("/tmp/demo"), expo_auto=False
        )
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-demo-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["claude"])

        mock_attach.assert_not_called()

    @patch("ai_shell.expo.attach")
    def test_expo_auto_disabled_in_config_still_honours_the_flag(
        self, mock_attach, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        from ai_shell.config import AiShellConfig

        mock_config.return_value = AiShellConfig(
            project_name="demo", project_dir=Path("/tmp/demo"), expo_auto=False
        )
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-demo-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["claude", "--expo"])

        mock_attach.assert_called_once()

    @patch("ai_shell.expo.attach")
    def test_no_expo_flag_skips_detection_entirely(
        self, mock_attach, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["claude", "--no-expo"])

        mock_attach.assert_not_called()

    @patch("ai_shell.expo.attach")
    def test_explicit_expo_failure_aborts_launch(
        self, mock_attach, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        from ai_shell.expo import ExpoError

        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager_cls.return_value = mock_manager
        mock_attach.side_effect = ExpoError("tunnel never came up")

        result = self.runner.invoke(cli, ["claude", "--expo"])

        assert result.exit_code != 0
        assert "tunnel never came up" in result.output
        mock_manager.run_interactive.assert_not_called()

    @patch("ai_shell.expo.attach")
    def test_auto_detected_expo_failure_does_not_block_the_agent(
        self, mock_attach, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        """A dev server that will not start must not cost you your Claude session."""
        from ai_shell.expo import ExpoError

        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager
        mock_attach.side_effect = ExpoError("tunnel never came up")

        result = self.runner.invoke(cli, ["claude"])

        assert result.exit_code == 0
        mock_manager.run_interactive.assert_called_once()

    @patch("ai_shell.expo.attach")
    def test_shell_does_not_auto_detect_expo(
        self, mock_attach, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["shell"])

        mock_attach.assert_not_called()

    @patch("ai_shell.expo.attach")
    def test_shell_expo_flag_still_works(
        self, mock_attach, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["shell", "--expo"])

        mock_attach.assert_called_once()

    @patch("ai_shell.expo.attach")
    def test_expo_attaches_before_codex_launch(
        self, mock_attach, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["codex", "--expo"])

        mock_attach.assert_called_once()

    @patch("ai_shell.expo.attach")
    def test_expo_attaches_before_opencode_launch(
        self, mock_attach, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        from ai_shell.config import AiShellConfig

        mock_config.return_value = AiShellConfig(project_name="demo", project_dir=Path("/tmp/demo"))
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-demo-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["opencode", "--expo"])

        mock_attach.assert_called_once()

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
    @patch("ai_shell.local_chrome.prepare_chrome_mcp", return_value="1 page")
    @patch("ai_shell.local_chrome.start_chrome_proxy")
    @patch("ai_shell.local_chrome.ensure_host_chrome", return_value=9222)
    def test_claude_local_chrome_injects_mcp_config(
        self,
        mock_ensure,
        mock_proxy,
        mock_prepare,
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
        config.claude_account = ""
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
    @patch("ai_shell.local_chrome.prepare_chrome_mcp", return_value="1 page")
    @patch("ai_shell.local_chrome.start_chrome_proxy")
    @patch("ai_shell.local_chrome.ensure_host_chrome", return_value=54321)
    def test_claude_local_chrome_retry_includes_mcp_config(
        self,
        mock_ensure,
        mock_proxy,
        mock_prepare,
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
        config.claude_account = ""
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
        config.claude_account = ""
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

        mock_check_bedrock.assert_called_once()
        args, kwargs = mock_check_bedrock.call_args
        assert args[0] == "augint-shell-test-dev"
        assert args[1] == bedrock_env
        assert "cache_ttl" in kwargs
        assert "model_id" in kwargs

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
        assert "--mdns" in cmd
        assert "--cors" in cmd
        assert "*" in cmd
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

    def test_opencode_web_mdns_domain_uses_project_slug(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        config = MagicMock()
        config.bedrock_profile = ""
        config.openai_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = Path("/tmp/my-project")
        config.project_name = "my-project"
        config.primary_coding_model = "qwen3-coder:30b-a3b-q4_K_M"
        mock_config.return_value = config

        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["opencode", "--web"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert "--mdns-domain" in cmd
        mdns_idx = cmd.index("--mdns-domain")
        assert cmd[mdns_idx + 1].endswith(".local")

    def test_opencode_web_password_hint(
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

        env_with_pass = dict(TEST_EXEC_ENV)
        env_with_pass["OPENCODE_SERVER_PASSWORD"] = "secret"
        mock_build_env.return_value = env_with_pass
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["opencode", "--web"])

        assert "Password protection enabled" in result.output

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

    @patch("ai_shell.cli.commands.tools.subprocess.run")
    def test_opencode_serve_starts_server(
        self, mock_subprocess, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
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
        mock_manager_cls.return_value = mock_manager

        with patch("ai_shell.cli.commands.tools.Path.cwd", return_value=Path("/tmp/test")):
            result = self.runner.invoke(cli, ["opencode", "serve"])

        mock_manager.exec_detached.assert_called_once()
        serve_cmd = mock_manager.exec_detached.call_args[0][1]
        assert "serve" in serve_cmd
        assert "--hostname" in serve_cmd
        assert "--mdns" in serve_cmd
        assert "--cors" in serve_cmd
        assert "http://localhost:" in result.output

    def test_opencode_attach_default_port(
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

        result = self.runner.invoke(cli, ["opencode", "attach"])

        mock_manager.exec_interactive.assert_called_once()
        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert cmd == ["opencode", "attach", "http://localhost:4096"]
        assert "Attaching" in result.output
        mock_check_bedrock.assert_not_called()

    def test_opencode_attach_custom_port(
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

        self.runner.invoke(cli, ["opencode", "attach", "--port", "8080"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert cmd == ["opencode", "attach", "http://localhost:8080"]

    def test_opencode_attach_skips_bedrock_and_model(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        config = MagicMock()
        config.bedrock_profile = "sandbox"
        config.openai_profile = ""
        config.ai_profile = "sandbox"
        config.aws_region = "us-east-1"
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

        self.runner.invoke(cli, ["opencode", "attach"])

        mock_manager.exec_interactive.assert_called_once()
        mock_manager.exec_detached.assert_not_called()
        mock_check_bedrock.assert_not_called()
        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert "--model" not in cmd

    @patch("ai_shell.cli.commands.tools.subprocess.run")
    def test_opencode_status_running(
        self, mock_subprocess, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        config = MagicMock()
        config.bedrock_profile = ""
        config.openai_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = Path("/tmp/test")
        config.project_name = "test"
        mock_config.return_value = config

        mock_subprocess.side_effect = [
            MagicMock(returncode=0, stdout="true\n"),
            MagicMock(
                returncode=0,
                stdout="123 opencode serve --port 4096\n456 opencode attach http://localhost:4096\n",
            ),
            # docker port lookup: live binding is authoritative for the URL
            MagicMock(returncode=0, stdout="0.0.0.0:23456\n"),
        ]

        result = self.runner.invoke(cli, ["opencode", "status"])

        assert "running" in result.output.lower()
        assert "1 attached" in result.output
        assert "23456" in result.output

    @patch("ai_shell.cli.commands.tools.subprocess.run")
    def test_opencode_status_not_running(
        self, mock_subprocess, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        config = MagicMock()
        config.bedrock_profile = ""
        config.openai_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = Path("/tmp/test")
        config.project_name = "test"
        mock_config.return_value = config

        mock_subprocess.return_value = MagicMock(returncode=1, stdout="")

        result = self.runner.invoke(cli, ["opencode", "status"])

        assert "not running" in result.output.lower()

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

    @patch("ai_shell.cli.commands.tools.subprocess.run")
    def test_uses_custom_model_id(self, mock_run):
        from ai_shell.cli.commands.tools import _check_bedrock_access

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        exec_env = {"AWS_PROFILE": "sandbox", "AWS_REGION": "us-east-1"}

        _check_bedrock_access("test-container", exec_env, model_id="anthropic.claude-opus-4-8")

        args = mock_run.call_args[0][0]
        shell_cmd = args[-1]
        assert "anthropic.claude-opus-4-8" in shell_cmd

    @patch("ai_shell.cli.commands.tools.subprocess.run")
    def test_falls_back_to_default_model(self, mock_run):
        from ai_shell.cli.commands.tools import _check_bedrock_access
        from ai_shell.defaults import DEFAULT_BEDROCK_MODEL

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        exec_env = {"AWS_PROFILE": "rd", "AWS_REGION": "us-east-1"}

        _check_bedrock_access("test-container", exec_env)

        args = mock_run.call_args[0][0]
        shell_cmd = args[-1]
        assert DEFAULT_BEDROCK_MODEL in shell_cmd


class TestHelpShortFlag:
    """Verify -h works as alias for --help across all groups and commands."""

    def setup_method(self):
        self.runner = CliRunner()

    def test_podman_docker_host_sets_container_host(self, monkeypatch):
        import os

        monkeypatch.setenv("DOCKER_HOST", "unix:///run/user/2004/podman/podman.sock")
        monkeypatch.delenv("CONTAINER_HOST", raising=False)
        monkeypatch.delenv("CONTAINER_CONNECTION", raising=False)
        # --version exits before the group callback; a subcommand's --help does not.
        result = self.runner.invoke(cli, ["vpn", "--help"])
        assert result.exit_code == 0, result.output
        assert os.environ["CONTAINER_HOST"] == "unix:///run/user/2004/podman/podman.sock"

    def test_docker_socket_leaves_container_host_unset(self, monkeypatch):
        import os

        monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
        monkeypatch.delenv("CONTAINER_HOST", raising=False)
        self.runner.invoke(cli, ["vpn", "--help"])
        assert "CONTAINER_HOST" not in os.environ

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


ACCOUNT_PREFIX = ["env", "-u", "ANTHROPIC_API_KEY", "-u", "ANTHROPIC_AUTH_TOKEN"]


@patch("ai_shell.expo.attach")
@patch("ai_shell.cli.commands.tools.ContainerManager")
@patch("ai_shell.cli.commands.tools.load_config")
class TestClaudeAccount:
    """``claude --account`` resolves tokens through the real env builder."""

    @pytest.fixture(autouse=True)
    def _accounts(self, isolate_home):
        env_path = isolate_home / ".augint" / ".env"
        env_path.parent.mkdir()
        env_path.write_text(
            "CLAUDE_CODE_OAUTH_TOKEN_WOXOM=tok-woxom\n"
            "CLAUDE_CODE_OAUTH_TOKEN_AI=tok-ai\n"
            "ANTHROPIC_API_KEY=sk-ant-global\n"
        )
        self.runner = CliRunner()

    def _setup(self, mock_config, mock_manager_cls, account: str = ""):
        from ai_shell.config import AiShellConfig

        mock_config.return_value = AiShellConfig(
            project_name="demo", project_dir=Path("/tmp/demo"), claude_account=account
        )
        manager = MagicMock()
        manager.ensure_dev_container.return_value = "augint-shell-demo-dev"
        manager.run_interactive.return_value = (0, 30.0)
        manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = manager
        return manager

    def test_account_injects_token_and_unsets_api_keys(
        self, mock_config, mock_manager_cls, mock_expo
    ):
        manager = self._setup(mock_config, mock_manager_cls)

        result = self.runner.invoke(cli, ["claude", "--account", "woxom"])

        assert result.exit_code == 0, result.output
        cmd = manager.run_interactive.call_args[0][1]
        assert cmd == [*ACCOUNT_PREFIX, "claude", "--dangerously-skip-permissions", "-c"]
        env = manager.run_interactive.call_args[1]["extra_env"]
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "tok-woxom"
        assert "ANTHROPIC_API_KEY" not in env
        assert "CLAUDE_CODE_OAUTH_TOKEN_AI" not in env
        assert "account=woxom" in result.output

    def test_retry_keeps_account_prefix(self, mock_config, mock_manager_cls, mock_expo):
        manager = self._setup(mock_config, mock_manager_cls)
        manager.run_interactive.return_value = (1, 1.0)

        self.runner.invoke(cli, ["claude", "--account", "ai"])

        cmd_fresh = manager.exec_interactive.call_args[0][1]
        assert cmd_fresh == [*ACCOUNT_PREFIX, "claude", "--dangerously-skip-permissions"]
        env = manager.exec_interactive.call_args[1]["extra_env"]
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "tok-ai"

    def test_no_account_is_unchanged(self, mock_config, mock_manager_cls, mock_expo):
        manager = self._setup(mock_config, mock_manager_cls)

        self.runner.invoke(cli, ["claude"])

        cmd = manager.run_interactive.call_args[0][1]
        assert cmd == ["claude", "--dangerously-skip-permissions", "-c"]
        env = manager.run_interactive.call_args[1]["extra_env"]
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
        assert env["ANTHROPIC_API_KEY"] == "sk-ant-global"

    def test_config_account_used_without_flag(self, mock_config, mock_manager_cls, mock_expo):
        manager = self._setup(mock_config, mock_manager_cls, account="ai")

        self.runner.invoke(cli, ["claude"])

        env = manager.run_interactive.call_args[1]["extra_env"]
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "tok-ai"

    def test_default_flag_overrides_config_account(self, mock_config, mock_manager_cls, mock_expo):
        manager = self._setup(mock_config, mock_manager_cls, account="ai")

        self.runner.invoke(cli, ["claude", "--account", "default"])

        cmd = manager.run_interactive.call_args[0][1]
        assert cmd[0] == "claude"
        env = manager.run_interactive.call_args[1]["extra_env"]
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in env

    def test_account_without_value_lists_accounts(self, mock_config, mock_manager_cls, mock_expo):
        manager = self._setup(mock_config, mock_manager_cls, account="woxom")

        result = self.runner.invoke(cli, ["claude", "--account"])

        assert result.exit_code == 0, result.output
        for name in ("default", "ai", "woxom"):
            assert name in result.output
        assert "CLAUDE_CODE_OAUTH_TOKEN_WOXOM" in result.output
        assert "tok-" not in result.output
        manager.ensure_dev_container.assert_not_called()

    def test_unknown_account_fails_loudly(self, mock_config, mock_manager_cls, mock_expo):
        manager = self._setup(mock_config, mock_manager_cls)

        result = self.runner.invoke(cli, ["claude", "--account", "nope"])

        assert result.exit_code == 1
        assert "CLAUDE_CODE_OAUTH_TOKEN_NOPE" in result.output
        assert "default, ai, woxom" in result.output
        manager.run_interactive.assert_not_called()

    def test_account_with_aws_fails_loudly(self, mock_config, mock_manager_cls, mock_expo):
        manager = self._setup(mock_config, mock_manager_cls)

        result = self.runner.invoke(cli, ["claude", "--aws", "--account", "woxom"])

        assert result.exit_code == 1
        assert "Bedrock" in result.output
        manager.run_interactive.assert_not_called()

    def test_team_mode_uses_account(self, mock_config, mock_manager_cls, mock_expo):
        manager = self._setup(mock_config, mock_manager_cls)

        self.runner.invoke(cli, ["claude", "--team", "--account", "woxom"])

        cmd = manager.exec_interactive.call_args[0][1]
        assert cmd[: len(ACCOUNT_PREFIX) + 1] == [*ACCOUNT_PREFIX, "claude"]
        env = manager.exec_interactive.call_args[1]["extra_env"]
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "tok-woxom"

    @patch("ai_shell.cli.commands.tools.subprocess.run")
    @patch("ai_shell.cli.commands.tools._setup_worktree", return_value="/wt")
    def test_multi_passes_token_via_tmux_session_env(
        self,
        mock_worktree,
        mock_run,
        mock_config,
        mock_manager_cls,
        mock_expo,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)  # no workspace.yaml -> single-repo multi
        self._setup(mock_config, mock_manager_cls)
        mock_run.return_value = MagicMock(returncode=1, stderr="")

        self.runner.invoke(cli, ["claude", "--multi", "--account", "woxom"], input="2\n")

        calls = [c[0][0] for c in mock_run.call_args_list]
        new_session = next(c for c in calls if "new-session" in c)
        assert "CLAUDE_CODE_OAUTH_TOKEN=tok-woxom" in new_session
        send_keys = [c for c in calls if "send-keys" in c]
        assert send_keys
        for c in send_keys:
            assert "unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN;" in " ".join(c)
            assert "tok-woxom" not in " ".join(c)


RC_PREFIX = [
    "env",
    "-u",
    "ANTHROPIC_API_KEY",
    "-u",
    "ANTHROPIC_AUTH_TOKEN",
    "-u",
    "CLAUDE_CODE_OAUTH_TOKEN",
]


@patch("ai_shell.expo.attach")
@patch("ai_shell.cli.commands.tools.ContainerManager")
@patch("ai_shell.cli.commands.tools.load_config")
class TestClaudeRemoteControl:
    """``claude --rc`` / ``--login`` use login profiles through the real env builder."""

    @pytest.fixture(autouse=True)
    def _accounts(self, isolate_home):
        self.home = isolate_home
        env_path = isolate_home / ".augint" / ".env"
        env_path.parent.mkdir()
        env_path.write_text(
            "CLAUDE_CODE_OAUTH_TOKEN_WOXOM=tok-woxom\nANTHROPIC_API_KEY=sk-ant-global\n"
        )
        self.runner = CliRunner()
        # The piped login talks to a real subprocess; stub it at the module seam.
        with patch("ai_shell.claude_login.run_piped_login", return_value=0) as piped:
            self.piped_login = piped
            yield

    def _setup(self, mock_config, mock_manager_cls, config=None, logged_in=True):
        from ai_shell.config import AiShellConfig

        mock_config.return_value = config or AiShellConfig(
            project_name="demo", project_dir=Path("/tmp/demo")
        )
        manager = MagicMock()
        manager.ensure_dev_container.return_value = "augint-shell-demo-dev"
        manager.exec_capture.return_value = MagicMock(
            returncode=0 if logged_in else 1, stdout="", stderr=""
        )
        manager.run_interactive.return_value = (0, 30.0)
        manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = manager
        return manager

    def test_rc_default_account_runs_server_mode_without_api_keys(
        self, mock_config, mock_manager_cls, mock_expo
    ):
        manager = self._setup(mock_config, mock_manager_cls)

        result = self.runner.invoke(cli, ["claude", "--rc"])

        assert result.exit_code == 0, result.output
        cmd = manager.exec_interactive.call_args[0][1]
        assert cmd == [
            *RC_PREFIX,
            "claude",
            "remote-control",
            "--name",
            "demo",
            "--permission-mode",
            "bypassPermissions",
        ]
        env = manager.exec_interactive.call_args[1]["extra_env"]
        assert "ANTHROPIC_API_KEY" not in env
        assert "CLAUDE_CONFIG_DIR" not in env
        # Logged in already: status checked, no login flow.
        status_cmd = manager.exec_capture.call_args[0][1]
        assert status_cmd == [*RC_PREFIX, "claude", "auth", "status"]
        manager.run_interactive.assert_not_called()

    def test_rc_with_token_account_uses_login_profile(
        self, mock_config, mock_manager_cls, mock_expo
    ):
        manager = self._setup(mock_config, mock_manager_cls)

        result = self.runner.invoke(cli, ["claude", "--rc", "--account", "woxom"])

        assert result.exit_code == 0, result.output
        cmd = manager.exec_interactive.call_args[0][1]
        assert cmd[: len(RC_PREFIX) + 4] == [
            *RC_PREFIX,
            "claude",
            "remote-control",
            "--name",
            "demo (woxom)",
        ]
        env = manager.exec_interactive.call_args[1]["extra_env"]
        assert env["CLAUDE_CONFIG_DIR"] == "/root/.augint/claude-accounts/woxom"
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
        assert "ANTHROPIC_API_KEY" not in env
        assert (self.home / ".augint" / "claude-accounts" / "woxom").is_dir()
        assert "account=woxom, login profile" in result.output

    def test_rc_runs_auth_login_when_not_logged_in(self, mock_config, mock_manager_cls, mock_expo):
        manager = self._setup(mock_config, mock_manager_cls, logged_in=False)

        result = self.runner.invoke(cli, ["claude", "--rc", "--account", "mike"])

        assert result.exit_code == 0, result.output
        # Login runs over pipes from the host, not through the container TTY.
        self.piped_login.assert_called_once()
        exec_args_call = manager.exec_args.call_args
        assert exec_args_call[0][1] == [*RC_PREFIX, "claude", "auth", "login"]
        assert exec_args_call[1]["extra_env"]["CLAUDE_CONFIG_DIR"] == (
            "/root/.augint/claude-accounts/mike"
        )
        assert exec_args_call[1]["workdir"] == "/root/projects/demo"
        assert exec_args_call[1]["stdin"] is True
        manager.run_interactive.assert_not_called()
        assert "No claude.ai login found" in result.output
        # Then the server starts.
        assert "remote-control" in manager.exec_interactive.call_args[0][1]

    def test_rc_falls_back_to_tty_login_when_no_url_appears(
        self, mock_config, mock_manager_cls, mock_expo
    ):
        manager = self._setup(mock_config, mock_manager_cls, logged_in=False)
        self.piped_login.return_value = None

        result = self.runner.invoke(cli, ["claude", "--rc", "--account", "mike"])

        assert result.exit_code == 0, result.output
        login_cmd = manager.run_interactive.call_args[0][1]
        assert login_cmd == [*RC_PREFIX, "claude", "auth", "login"]
        assert "remote-control" in manager.exec_interactive.call_args[0][1]

    def test_rc_relogs_in_when_credential_is_not_claude_ai(
        self, mock_config, mock_manager_cls, mock_expo
    ):
        manager = self._setup(mock_config, mock_manager_cls)
        manager.exec_capture.return_value = MagicMock(
            returncode=0, stdout='{"loggedIn": true, "authMethod": "api_key"}', stderr=""
        )

        result = self.runner.invoke(cli, ["claude", "--rc"])

        assert result.exit_code == 0, result.output
        self.piped_login.assert_called_once()
        assert "api_key" in result.output

    def test_rc_accepts_claude_ai_auth_method(self, mock_config, mock_manager_cls, mock_expo):
        manager = self._setup(mock_config, mock_manager_cls)
        manager.exec_capture.return_value = MagicMock(
            returncode=0, stdout='{"loggedIn": true, "authMethod": "claude.ai"}', stderr=""
        )

        self.runner.invoke(cli, ["claude", "--rc"])

        manager.run_interactive.assert_not_called()

    def test_login_profile_without_rc_accepts_any_auth_method(
        self, mock_config, mock_manager_cls, mock_expo
    ):
        (self.home / ".augint" / "claude-accounts" / "mike").mkdir(parents=True)
        manager = self._setup(mock_config, mock_manager_cls)
        manager.exec_interactive.side_effect = None
        manager.exec_capture.return_value = MagicMock(
            returncode=0, stdout='{"authMethod": "api_key"}', stderr=""
        )

        self.runner.invoke(cli, ["claude", "--account", "mike"])

        assert manager.run_interactive.call_count == 1
        assert "auth" not in manager.run_interactive.call_args[0][1]

    def test_rc_rejects_foreign_anthropic_base_url(self, mock_config, mock_manager_cls, mock_expo):
        (self.home / ".augint" / ".env").write_text(
            "ANTHROPIC_BASE_URL=https://gateway.example.com/v1\n"
        )
        manager = self._setup(mock_config, mock_manager_cls)

        result = self.runner.invoke(cli, ["claude", "--rc"])

        assert result.exit_code == 1
        assert "ANTHROPIC_BASE_URL" in result.output
        manager.exec_interactive.assert_not_called()

    def test_rc_allows_official_anthropic_base_url(self, mock_config, mock_manager_cls, mock_expo):
        (self.home / ".augint" / ".env").write_text(
            "ANTHROPIC_BASE_URL=https://api.anthropic.com\n"
        )
        manager = self._setup(mock_config, mock_manager_cls)

        result = self.runner.invoke(cli, ["claude", "--rc"])

        assert result.exit_code == 0, result.output
        assert "remote-control" in manager.exec_interactive.call_args[0][1]

    def test_rc_aborts_when_auth_login_fails(self, mock_config, mock_manager_cls, mock_expo):
        manager = self._setup(mock_config, mock_manager_cls, logged_in=False)
        self.piped_login.return_value = 1

        result = self.runner.invoke(cli, ["claude", "--rc", "--account", "mike"])

        assert result.exit_code == 1
        assert "claude auth login" in result.output
        manager.exec_interactive.assert_not_called()

    def test_rc_custom_name_and_safe_mode(self, mock_config, mock_manager_cls, mock_expo):
        manager = self._setup(mock_config, mock_manager_cls)

        self.runner.invoke(cli, ["claude", "--safe", "--rc", "Mike laptop", "--", "--verbose"])

        cmd = manager.exec_interactive.call_args[0][1]
        assert cmd == [*RC_PREFIX, "claude", "remote-control", "--name", "Mike laptop", "--verbose"]

    @patch("ai_shell.cli.commands.tools._inject_mcp_config")
    @patch("ai_shell.local_chrome.write_mcp_config", return_value=Path("/tmp/chrome-mcp.json"))
    @patch("ai_shell.local_chrome.prepare_chrome_mcp", return_value="1 page")
    @patch("ai_shell.local_chrome.start_chrome_proxy")
    @patch("ai_shell.local_chrome.ensure_host_chrome", return_value=45678)
    def test_rc_with_local_chrome_registers_mcp_at_local_scope(
        self,
        mock_ensure,
        mock_proxy,
        mock_prepare,
        mock_write,
        mock_inject,
        mock_config,
        mock_manager_cls,
        mock_expo,
    ):
        manager = self._setup(mock_config, mock_manager_cls)

        result = self.runner.invoke(cli, ["claude", "--rc", "--account", "woxom", "--local-chrome"])

        assert result.exit_code == 0, result.output
        mock_ensure.assert_called_once_with(
            "augint-shell-demo-dev",
            project_name="demo",
            project_dir=Path("/tmp/demo"),
            profile="woxom",
        )
        mcp_calls = [c for c in manager.exec_capture.call_args_list if "mcp" in c[0][1]]
        assert [c[0][1][:3] for c in mcp_calls] == [
            ["claude", "mcp", "remove"],
            ["claude", "mcp", "add-json"],
        ]
        add_cmd = mcp_calls[1][0][1]
        assert add_cmd[3:6] == ["--scope", "local", "chrome-devtools"]
        assert "http://localhost:45678" in add_cmd[6]
        assert mcp_calls[1][1]["workdir"] == "/root/projects/demo"
        assert mcp_calls[1][1]["extra_env"]["CLAUDE_CONFIG_DIR"].endswith("/woxom")
        # Server mode cannot take --mcp-config.
        cmd = manager.exec_interactive.call_args[0][1]
        assert "--mcp-config" not in cmd

    @patch("ai_shell.cli.commands.tools._inject_mcp_config")
    @patch("ai_shell.local_chrome.write_mcp_config", return_value=Path("/tmp/chrome-mcp.json"))
    @patch("ai_shell.local_chrome.prepare_chrome_mcp", return_value="1 page")
    @patch("ai_shell.local_chrome.start_chrome_proxy")
    @patch("ai_shell.local_chrome.ensure_host_chrome", return_value=45678)
    def test_rc_local_chrome_uses_account_proxy(
        self,
        mock_ensure,
        mock_proxy,
        mock_prepare,
        mock_write,
        mock_inject,
        mock_config,
        mock_manager_cls,
        mock_expo,
    ):
        from ai_shell.config import AiShellConfig, ClaudeAccountConfig

        config = AiShellConfig(project_name="demo", project_dir=Path("/tmp/demo"))
        config.chrome_proxy = "http://127.0.0.1:3128"
        config.claude_accounts["woxom"] = ClaudeAccountConfig(chrome_proxy="http://127.0.0.1:8888")
        self._setup(mock_config, mock_manager_cls, config=config)

        result = self.runner.invoke(cli, ["claude", "--rc", "--account", "woxom", "--local-chrome"])

        assert result.exit_code == 0, result.output
        assert mock_ensure.call_args[1]["proxy"] == "http://127.0.0.1:8888"
        assert "proxy: http://127.0.0.1:8888" in result.output

    @patch("ai_shell.cli.commands.tools._inject_mcp_config")
    @patch("ai_shell.local_chrome.write_mcp_config", return_value=Path("/tmp/chrome-mcp.json"))
    @patch("ai_shell.local_chrome.prepare_chrome_mcp", return_value="1 page")
    @patch("ai_shell.local_chrome.start_chrome_proxy")
    @patch("ai_shell.local_chrome.ensure_host_chrome", return_value=45678)
    def test_rc_chrome_proxy_flag_overrides_config(
        self,
        mock_ensure,
        mock_proxy,
        mock_prepare,
        mock_write,
        mock_inject,
        mock_config,
        mock_manager_cls,
        mock_expo,
    ):
        from ai_shell.config import AiShellConfig

        config = AiShellConfig(project_name="demo", project_dir=Path("/tmp/demo"))
        config.chrome_proxy = "http://127.0.0.1:3128"
        self._setup(mock_config, mock_manager_cls, config=config)

        result = self.runner.invoke(
            cli,
            [
                "claude",
                "--rc",
                "--account",
                "woxom",
                "--local-chrome",
                "--chrome-proxy",
                "socks5://127.0.0.1:1080",
            ],
        )

        assert result.exit_code == 0, result.output
        assert mock_ensure.call_args[1]["proxy"] == "socks5://127.0.0.1:1080"

    @patch("ai_shell.cli.commands.tools._inject_mcp_config")
    @patch("ai_shell.local_chrome.write_mcp_config", return_value=Path("/tmp/chrome-mcp.json"))
    @patch("ai_shell.local_chrome.prepare_chrome_mcp", return_value="1 page")
    @patch("ai_shell.local_chrome.start_chrome_proxy")
    @patch("ai_shell.local_chrome.ensure_host_chrome", return_value=45678)
    @patch("ai_shell.vpn.ensure_vpn_for_config", return_value="http://127.0.0.1:8888")
    def test_rc_chrome_proxy_vpn_starts_the_vpn_container(
        self,
        mock_vpn,
        mock_ensure,
        mock_proxy,
        mock_prepare,
        mock_write,
        mock_inject,
        mock_config,
        mock_manager_cls,
        mock_expo,
    ):
        from contextlib import contextmanager

        from ai_shell.config import AiShellConfig
        from ai_shell.typeahead import TypeaheadBuffer

        config = AiShellConfig(project_name="demo", project_dir=Path("/tmp/demo"))
        config.chrome_proxy = "vpn"
        manager = self._setup(mock_config, mock_manager_cls, config=config)

        # The VPN step may prompt for the NordVPN token, so it must run after
        # the typeahead capture has given the terminal back.
        order: list[str] = []

        @contextmanager
        def fake_capture():
            order.append("capture-start")
            yield TypeaheadBuffer()
            order.append("capture-end")

        mock_vpn.side_effect = lambda *a, **k: (order.append("vpn"), "http://127.0.0.1:8888")[1]

        with patch("ai_shell.cli.commands.tools.capture_typeahead", fake_capture):
            result = self.runner.invoke(
                cli, ["claude", "--rc", "--account", "woxom", "--local-chrome"]
            )

        assert result.exit_code == 0, result.output
        mock_vpn.assert_called_once()
        assert mock_vpn.call_args[0][0] is manager
        assert mock_vpn.call_args[0][1] is config
        assert mock_ensure.call_args[1]["proxy"] == "http://127.0.0.1:8888"
        assert order == ["capture-start", "capture-end", "vpn"]

    @patch("ai_shell.cli.commands.tools._inject_mcp_config")
    @patch("ai_shell.local_chrome.write_mcp_config", return_value=Path("/tmp/chrome-mcp.json"))
    @patch("ai_shell.local_chrome.prepare_chrome_mcp", return_value="1 page")
    @patch("ai_shell.local_chrome.start_chrome_proxy")
    @patch("ai_shell.local_chrome.ensure_host_chrome", return_value=45678)
    @patch("ai_shell.local_chrome.launch_plain_chrome")
    def test_rc_local_chrome_signs_in_through_a_plain_window_first(
        self,
        mock_plain,
        mock_ensure,
        mock_proxy,
        mock_prepare,
        mock_write,
        mock_inject,
        mock_config,
        mock_manager_cls,
        mock_expo,
    ):
        """Not logged in + --local-chrome: plain window, code, close, then the debug-port Chrome."""
        from ai_shell.config import AiShellConfig, ClaudeAccountConfig

        config = AiShellConfig(project_name="demo", project_dir=Path("/tmp/demo"))
        config.claude_accounts["woxom"] = ClaudeAccountConfig(chrome_proxy="http://127.0.0.1:8888")
        manager = self._setup(mock_config, mock_manager_cls, config=config)

        def exec_capture(container, cmd, **_kwargs):
            # Not logged in; every other captured command (claude mcp ...) succeeds.
            code = 1 if cmd[-2:] == ["auth", "status"] else 0
            return MagicMock(returncode=code, stdout="", stderr="")

        manager.exec_capture.side_effect = exec_capture
        order: list[str] = []
        window = MagicMock()
        window.close.side_effect = lambda: order.append("close") or True
        mock_plain.side_effect = lambda **kw: order.append("plain") or window
        mock_ensure.side_effect = lambda *a, **kw: order.append("debug-chrome") or 45678
        url = "https://claude.ai/oauth/authorize?code=true&client_id=abc"

        def fake_run(args, *, open_url, prompt_code, echo, **_kw):
            assert open_url(url) is True
            return 0

        self.piped_login.side_effect = fake_run

        result = self.runner.invoke(cli, ["claude", "--rc", "--account", "woxom", "--local-chrome"])

        assert result.exit_code == 0, result.output
        assert order == ["plain", "close", "debug-chrome"]
        assert mock_plain.call_args[1] == {
            "project_name": "demo",
            "project_dir": Path("/tmp/demo"),
            "profile": "woxom",
            "proxy": "http://127.0.0.1:8888",
            "url": url,
            "close_running": True,
        }
        assert "no DevTools port" in result.output
        # The status check ran once; no second login after the plain one.
        status_calls = [
            c for c in manager.exec_capture.call_args_list if c[0][1][-2:] == ["auth", "status"]
        ]
        assert len(status_calls) == 1
        assert "remote-control" in manager.exec_interactive.call_args[0][1]

    def test_login_prints_url_even_when_chrome_opened_it(
        self, mock_config, mock_manager_cls, mock_expo
    ):
        """A Google-SSO account cannot sign in inside the debug-port Chrome."""
        from ai_shell.cli.commands.tools import _piped_claude_login

        manager = self._setup(mock_config, mock_manager_cls)
        manager.exec_args.return_value = ["docker", "exec", "c", "claude", "auth", "login"]
        url = "https://claude.ai/oauth/authorize?code=true&client_id=abc&state=xyz"
        seen: dict[str, object] = {}

        def fake_run(args, *, open_url, prompt_code, echo, **_kwargs):
            seen["opened"] = open_url(url)
            return 0

        with (
            patch("ai_shell.claude_login.run_piped_login", side_effect=fake_run),
            patch("ai_shell.claude_login.open_in_chrome", return_value=True) as opened,
            patch("ai_shell.cli.commands.tools.console") as console,
        ):
            code = _piped_claude_login(
                manager,
                "c",
                ["claude", "auth", "login"],
                exec_env={},
                workdir=None,
                chrome_port=45678,
                chrome_profile="woxom",
            )

        assert code == 0
        assert seen["opened"] is True
        opened.assert_called_once_with(45678, url)
        printed = [str(c.args[0]) for c in console.print.call_args_list]
        assert any(url == line for line in printed)
        assert any("other browser" in line for line in printed)

    def test_rc_incompatible_with_multi_team_interactive(
        self, mock_config, mock_manager_cls, mock_expo
    ):
        manager = self._setup(mock_config, mock_manager_cls)
        for flag in ("--multi", "--team", "--interactive"):
            result = self.runner.invoke(cli, ["claude", "--rc", flag])
            assert result.exit_code == 1, flag
            assert "incompatible" in result.output
        manager.ensure_dev_container.assert_not_called()

    def test_rc_rejects_bedrock(self, mock_config, mock_manager_cls, mock_expo):
        manager = self._setup(mock_config, mock_manager_cls)

        result = self.runner.invoke(cli, ["claude", "--rc", "--aws"])

        assert result.exit_code == 1
        assert "Bedrock" in result.output
        manager.exec_interactive.assert_not_called()

    def test_login_flag_creates_profile_and_launches_normal_session(
        self, mock_config, mock_manager_cls, mock_expo
    ):
        manager = self._setup(mock_config, mock_manager_cls)
        manager.exec_interactive.side_effect = None

        result = self.runner.invoke(cli, ["claude", "--login", "--account", "mike"])

        assert result.exit_code == 0, result.output
        # Forced login runs without checking status first.
        assert not any("status" in c[0][1] for c in manager.exec_capture.call_args_list)
        self.piped_login.assert_called_once()
        assert manager.exec_args.call_args[0][1] == [*RC_PREFIX, "claude", "auth", "login"]
        calls = manager.run_interactive.call_args_list
        assert calls[0][0][1] == [*RC_PREFIX, "claude", "--dangerously-skip-permissions", "-c"]
        env = calls[0][1]["extra_env"]
        assert env["CLAUDE_CONFIG_DIR"] == "/root/.augint/claude-accounts/mike"
        assert "ANTHROPIC_API_KEY" not in env

    def test_account_with_only_login_profile_is_used_without_flags(
        self, mock_config, mock_manager_cls, mock_expo
    ):
        (self.home / ".augint" / "claude-accounts" / "mike").mkdir(parents=True)
        manager = self._setup(mock_config, mock_manager_cls)
        manager.exec_interactive.side_effect = None

        result = self.runner.invoke(cli, ["claude", "--account", "mike"])

        assert result.exit_code == 0, result.output
        status_cmd = manager.exec_capture.call_args[0][1]
        assert status_cmd == [*RC_PREFIX, "claude", "auth", "status"]
        cmd = manager.run_interactive.call_args[0][1]
        assert cmd == [*RC_PREFIX, "claude", "--dangerously-skip-permissions", "-c"]
        env = manager.run_interactive.call_args[1]["extra_env"]
        assert env["CLAUDE_CONFIG_DIR"] == "/root/.augint/claude-accounts/mike"

    def test_token_account_skips_login_check(self, mock_config, mock_manager_cls, mock_expo):
        manager = self._setup(mock_config, mock_manager_cls)
        manager.exec_interactive.side_effect = None

        self.runner.invoke(cli, ["claude", "--account", "woxom"])

        manager.exec_capture.assert_not_called()

    def test_account_listing_shows_login_profiles_and_chrome(
        self, mock_config, mock_manager_cls, mock_expo
    ):
        from ai_shell.config import AiShellConfig, ClaudeAccountConfig

        (self.home / ".augint" / "claude-accounts" / "mike").mkdir(parents=True)
        (self.home / ".augint" / "claude-accounts" / "woxom").mkdir(parents=True)
        config = AiShellConfig(
            project_name="demo",
            project_dir=Path("/tmp/demo"),
            claude_account="mike",
            claude_accounts={"mike": ClaudeAccountConfig(chrome_profile="mike-browser")},
        )
        manager = self._setup(mock_config, mock_manager_cls, config=config)

        result = self.runner.invoke(cli, ["claude", "--account"])

        assert result.exit_code == 0, result.output
        # Rich wraps at spaces, so assert on space-free tokens only.
        assert "~/.augint/claude-accounts/mike" in result.output
        assert "CLAUDE_CODE_OAUTH_TOKEN_WOXOM" in result.output
        assert "~/.augint/claude-accounts/woxom" in result.output
        assert "mike-browser" in result.output
        assert "--rc" in result.output
        assert "tok-" not in result.output
        manager.ensure_dev_container.assert_not_called()

    def test_account_listing_includes_configured_accounts_without_login(
        self, mock_config, mock_manager_cls, mock_expo
    ):
        from ai_shell.config import AiShellConfig, ClaudeAccountConfig

        config = AiShellConfig(
            project_name="demo",
            project_dir=Path("/tmp/demo"),
            claude_accounts={"adam": ClaudeAccountConfig(local_chrome=True)},
        )
        self._setup(mock_config, mock_manager_cls, config=config)

        result = self.runner.invoke(cli, ["claude", "--account"])

        assert result.exit_code == 0, result.output
        assert "adam" in result.output
        assert "configured only" in result.output
        assert "local_chrome: true" in result.output

    @patch("ai_shell.cli.commands.tools._inject_mcp_config")
    @patch("ai_shell.local_chrome.write_mcp_config", return_value=Path("/tmp/chrome-mcp.json"))
    @patch("ai_shell.local_chrome.prepare_chrome_mcp", return_value="1 page")
    @patch("ai_shell.local_chrome.start_chrome_proxy")
    @patch("ai_shell.local_chrome.ensure_host_chrome", return_value=40001)
    def test_per_account_local_chrome_config_and_profile(
        self,
        mock_ensure,
        mock_proxy,
        mock_prepare,
        mock_write,
        mock_inject,
        mock_config,
        mock_manager_cls,
        mock_expo,
    ):
        from ai_shell.config import AiShellConfig, ClaudeAccountConfig

        config = AiShellConfig(
            project_name="demo",
            project_dir=Path("/tmp/demo"),
            claude_accounts={
                "woxom": ClaudeAccountConfig(chrome_profile="woxom-browser", local_chrome=True)
            },
        )
        manager = self._setup(mock_config, mock_manager_cls, config=config)
        manager.exec_interactive.side_effect = None

        result = self.runner.invoke(cli, ["claude", "--account", "woxom"])

        assert result.exit_code == 0, result.output
        mock_ensure.assert_called_once_with(
            "augint-shell-demo-dev",
            project_name="demo",
            project_dir=Path("/tmp/demo"),
            profile="woxom-browser",
        )
        cmd = manager.run_interactive.call_args[0][1]
        assert "--mcp-config" in cmd

    @patch("ai_shell.local_chrome.ensure_host_chrome")
    def test_per_account_local_chrome_false_overrides_global(
        self, mock_ensure, mock_config, mock_manager_cls, mock_expo
    ):
        from ai_shell.config import AiShellConfig, ClaudeAccountConfig

        config = AiShellConfig(
            project_name="demo",
            project_dir=Path("/tmp/demo"),
            local_chrome=True,
            claude_accounts={"woxom": ClaudeAccountConfig(local_chrome=False)},
        )
        manager = self._setup(mock_config, mock_manager_cls, config=config)
        manager.exec_interactive.side_effect = None

        result = self.runner.invoke(cli, ["claude", "--account", "woxom"])

        assert result.exit_code == 0, result.output
        mock_ensure.assert_not_called()


@patch("ai_shell.cli.commands.tools.load_config")
class TestChromeCommand:
    """``ai-shell chrome``: the account's window without the DevTools port."""

    def setup_method(self):
        self.runner = CliRunner()

    def _config(self, mock_config, **overrides):
        from ai_shell.config import AiShellConfig

        config = AiShellConfig(project_name="demo", project_dir=Path("/tmp/demo"))
        for key, value in overrides.items():
            setattr(config, key, value)
        mock_config.return_value = config
        return config

    @patch(
        "ai_shell.local_chrome.launch_plain_chrome",
        return_value=MagicMock(profile_dir="/home/u/account-mike"),
    )
    def test_opens_account_window_with_configured_proxy(self, mock_launch, mock_config):
        from ai_shell.config import ClaudeAccountConfig

        config = self._config(mock_config)
        config.claude_accounts["mike"] = ClaudeAccountConfig(chrome_proxy="http://127.0.0.1:8888")

        result = self.runner.invoke(
            cli, ["chrome", "--account", "mike", "https://accounts.google.com/"]
        )

        assert result.exit_code == 0, result.output
        mock_launch.assert_called_once_with(
            project_name="demo",
            project_dir=Path("/tmp/demo"),
            profile="mike",
            proxy="http://127.0.0.1:8888",
            url="https://accounts.google.com/",
        )
        assert "account 'mike'" in result.output
        assert "http://127.0.0.1:8888" in result.output

    @patch(
        "ai_shell.local_chrome.launch_plain_chrome",
        return_value=MagicMock(profile_dir="/home/u/demo"),
    )
    def test_defaults_to_project_window_and_flag_proxy(self, mock_launch, mock_config):
        self._config(mock_config)

        result = self.runner.invoke(cli, ["chrome", "--chrome-proxy", "socks5://127.0.0.1:1080"])

        assert result.exit_code == 0, result.output
        assert mock_launch.call_args[1]["profile"] is None
        assert mock_launch.call_args[1]["proxy"] == "socks5://127.0.0.1:1080"
        assert mock_launch.call_args[1]["url"] is None
        assert "project 'demo'" in result.output

    @patch("ai_shell.local_chrome.launch_plain_chrome")
    def test_reports_running_window(self, mock_launch, mock_config):
        from ai_shell.local_chrome import LocalChromeUnavailable

        self._config(mock_config)
        mock_launch.side_effect = LocalChromeUnavailable("A Chrome window already uses the profile")

        result = self.runner.invoke(cli, ["chrome", "--account", "mike"])

        assert result.exit_code != 0
        assert "already uses the profile" in result.output


@patch("ai_shell.cli.commands.vpn.ContainerManager")
@patch("ai_shell.cli.commands.vpn.load_config")
class TestVpnCommands:
    def setup_method(self):
        self.runner = CliRunner()

    def _config(self, mock_config):
        from ai_shell.config import AiShellConfig

        config = AiShellConfig(project_name="demo", project_dir=Path("/tmp/demo"))
        mock_config.return_value = config
        return config

    @patch("ai_shell.vpn.ensure_vpn_for_config", return_value="http://127.0.0.1:8888")
    def test_up_starts_and_prints_proxy(self, mock_ensure, mock_config, mock_manager_cls):
        config = self._config(mock_config)

        result = self.runner.invoke(cli, ["vpn", "up"])

        assert result.exit_code == 0, result.output
        assert mock_ensure.call_args[0][1] is config
        assert mock_ensure.call_args[1]["prompt_token"] is not None
        assert "http://127.0.0.1:8888" in result.output

    @patch("ai_shell.vpn.ensure_vpn_for_config")
    def test_up_reports_missing_credential(self, mock_ensure, mock_config, mock_manager_cls):
        from ai_shell.vpn import VpnUnavailable

        self._config(mock_config)
        mock_ensure.side_effect = VpnUnavailable("No NordVPN credential. Add NORDVPN_TOKEN=...")

        result = self.runner.invoke(cli, ["vpn", "up"])

        assert result.exit_code != 0
        assert "NORDVPN_TOKEN" in result.output

    @patch("ai_shell.vpn.remove_vpn", return_value=True)
    def test_down_removes(self, mock_remove, mock_config, mock_manager_cls):
        self._config(mock_config)
        result = self.runner.invoke(cli, ["vpn", "down"])
        assert result.exit_code == 0, result.output
        assert "removed" in result.output

    @patch(
        "ai_shell.vpn.vpn_status",
        return_value={
            "status": "running",
            "exit_address": "203.0.113.9",
            "proxy": "http://127.0.0.1:8888",
        },
    )
    def test_status_shows_exit_address(self, mock_status, mock_config, mock_manager_cls):
        self._config(mock_config)
        result = self.runner.invoke(cli, ["vpn", "status"])
        assert result.exit_code == 0, result.output
        assert "running" in result.output
        assert "203.0.113.9" in result.output
