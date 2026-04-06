"""Tests for CLI tool subcommands."""

from unittest.mock import MagicMock, patch

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


@patch("ai_shell.cli.commands.tools.build_dev_environment")
@patch("ai_shell.cli.commands.tools.ContainerManager")
@patch("ai_shell.cli.commands.tools.load_config")
class TestToolCommands:
    def setup_method(self):
        self.runner = CliRunner()

    def test_claude_default_uses_permissive_with_continue(
        self, mock_config, mock_manager_cls, mock_build_env
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

    def test_claude_retry_on_fast_failure(self, mock_config, mock_manager_cls, mock_build_env):
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

    def test_claude_no_retry_on_slow_failure(self, mock_config, mock_manager_cls, mock_build_env):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        # run_interactive fails slowly (user exited with error)
        mock_manager.run_interactive.return_value = (1, 30.0)
        mock_manager_cls.return_value = mock_manager

        result = self.runner.invoke(cli, ["claude"])

        mock_manager.exec_interactive.assert_not_called()
        assert result.exit_code == 1

    def test_claude_safe_mode(self, mock_config, mock_manager_cls, mock_build_env):
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

    def test_claude_with_extra_args(self, mock_config, mock_manager_cls, mock_build_env):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["claude", "--", "--debug"])

        cmd = mock_manager.run_interactive.call_args[0][1]
        assert cmd == ["claude", "--dangerously-skip-permissions", "-c", "--debug"]

    def test_codex_command(self, mock_config, mock_manager_cls, mock_build_env):
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

    def test_codex_safe_mode(self, mock_config, mock_manager_cls, mock_build_env):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["codex", "--safe"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert "--dangerously-bypass-approvals-and-sandbox" not in cmd

    def test_shell_command(self, mock_config, mock_manager_cls, mock_build_env):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.exec_interactive.side_effect = SystemExit(0)
        mock_manager_cls.return_value = mock_manager

        self.runner.invoke(cli, ["shell"])

        cmd = mock_manager.exec_interactive.call_args[0][1]
        assert cmd == ["/bin/bash"]
        assert mock_manager.exec_interactive.call_args[1]["extra_env"] == TEST_EXEC_ENV

    def test_aider_passes_model_and_env(self, mock_config, mock_manager_cls, mock_build_env):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        config = MagicMock()
        config.aider_model = "ollama_chat/qwen3.5:27b"
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
        assert "ollama_chat/qwen3.5:27b" in cmd
        assert "--yes-always" in cmd
        assert extra_env["OLLAMA_API_BASE"] == "http://host.docker.internal:11434"
        assert extra_env["GH_TOKEN"] == "test-token"

    def test_aider_safe_mode(self, mock_config, mock_manager_cls, mock_build_env):
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        config = MagicMock()
        config.aider_model = "ollama_chat/qwen3.5:27b"
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

    def test_opencode_init_calls_scaffold(self, mock_config, mock_manager_cls, mock_build_env):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with patch("ai_shell.scaffold.scaffold_opencode") as mock_scaffold:
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
        assert result.exit_code == 0

    def test_opencode_update_calls_scaffold_with_merge(
        self, mock_config, mock_manager_cls, mock_build_env
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
        self, mock_config, mock_manager_cls, mock_build_env
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
        self, mock_config, mock_manager_cls, mock_build_env
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

    def test_codex_init_calls_scaffold(self, mock_config, mock_manager_cls, mock_build_env):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with patch("ai_shell.scaffold.scaffold_codex") as mock_scaffold:
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
        assert result.exit_code == 0

    def test_codex_update_calls_scaffold_with_merge(
        self, mock_config, mock_manager_cls, mock_build_env
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
        self, mock_config, mock_manager_cls, mock_build_env
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
        self, mock_config, mock_manager_cls, mock_build_env
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

    def test_aider_init_calls_scaffold(self, mock_config, mock_manager_cls, mock_build_env):
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
        self, mock_config, mock_manager_cls, mock_build_env
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
        self, mock_config, mock_manager_cls, mock_build_env
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
        self, mock_config, mock_manager_cls, mock_build_env
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

    def test_claude_update_calls_merge(self, mock_config, mock_manager_cls, mock_build_env):
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
        self, mock_config, mock_manager_cls, mock_build_env
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

    def test_claude_init_does_not_call_merge(self, mock_config, mock_manager_cls, mock_build_env):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with (
                patch("ai_shell.scaffold.scaffold_claude"),
                patch("ai_shell.notes_merge.merge_notes_into_context") as mock_merge,
            ):
                self.runner.invoke(cli, ["claude", "--init"])

        mock_merge.assert_not_called()

    def test_claude_clean_does_not_call_merge(self, mock_config, mock_manager_cls, mock_build_env):
        with patch("ai_shell.cli.commands.tools.Path") as mock_path:
            mock_path.cwd.return_value = "/tmp/test"
            with (
                patch("ai_shell.scaffold.scaffold_claude"),
                patch("ai_shell.notes_merge.merge_notes_into_context") as mock_merge,
            ):
                self.runner.invoke(cli, ["claude", "--clean"])

        mock_merge.assert_not_called()

    def test_codex_update_calls_merge(self, mock_config, mock_manager_cls, mock_build_env):
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
        self, mock_config, mock_manager_cls, mock_build_env
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

    def test_opencode_update_calls_merge(self, mock_config, mock_manager_cls, mock_build_env):
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
        self, mock_config, mock_manager_cls, mock_build_env
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
        self, mock_config, mock_manager_cls, mock_build_env
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

    def test_claude_bedrock_launch_message(self, mock_config, mock_manager_cls, mock_build_env):
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
        self, mock_config, mock_manager_cls, mock_build_env
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

    def test_version_flag(self, mock_config, mock_manager_cls, mock_build_env):
        result = self.runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "ai-shell" in result.output
