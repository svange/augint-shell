"""Tests for --multi flag: selector, tmux builder, and CLI integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from ai_shell.cli.__main__ import cli
from ai_shell.selector import SelectionItem
from ai_shell.tmux import (
    PaneSpec,
    build_claude_pane_command,
    build_tmux_commands,
    select_layout,
)

TEST_EXEC_ENV = {
    "AWS_PROFILE": "",
    "AWS_REGION": "us-east-1",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_PAGER": "",
    "GH_TOKEN": "test-token",
    "GITHUB_TOKEN": "test-token",
    "IS_SANDBOX": "1",
}


# ── Tmux command builder tests ──────────────────────────────────────


class TestSelectLayout:
    def test_2_panes(self):
        assert select_layout(2) == "even-vertical"

    def test_3_panes(self):
        assert select_layout(3) == "main-horizontal"

    def test_4_panes(self):
        assert select_layout(4) == "tiled"

    def test_5_panes_defaults_to_tiled(self):
        assert select_layout(5) == "tiled"

    def test_1_pane_defaults_to_tiled(self):
        assert select_layout(1) == "tiled"


class TestBuildClaudePaneCommand:
    def test_default_includes_permissive_flags(self):
        cmd = build_claude_pane_command(repo_name="my-repo")
        assert "--dangerously-skip-permissions" in cmd
        assert "-c" in cmd
        assert "-n" in cmd
        assert "my-repo" in cmd
        assert "UV_PROJECT_ENVIRONMENT=/root/.cache/uv/venvs/my-repo" in cmd

    def test_safe_omits_permissive_flags(self):
        cmd = build_claude_pane_command(repo_name="my-repo", safe=True)
        assert "--dangerously-skip-permissions" not in cmd
        assert "-c" not in cmd
        assert "-n" in cmd
        assert "my-repo" in cmd

    def test_extra_args_appended(self):
        cmd = build_claude_pane_command(repo_name="my-repo", extra_args=("--debug", "--verbose"))
        assert "-- --debug --verbose" in cmd

    def test_uv_env_prefix(self):
        cmd = build_claude_pane_command(repo_name="woxom-crm")
        assert cmd.startswith("UV_PROJECT_ENVIRONMENT=/root/.cache/uv/venvs/woxom-crm ")


class TestPaneSpec:
    def test_construction(self):
        pane = PaneSpec(
            name="my-repo", command="claude -n my-repo", working_dir="/root/projects/my-repo"
        )
        assert pane.name == "my-repo"
        assert pane.command == "claude -n my-repo"
        assert pane.working_dir == "/root/projects/my-repo"


class TestBuildTmuxCommands:
    def test_empty_panes_returns_empty(self):
        assert build_tmux_commands("container", "session", []) == []

    def test_2_panes_correct_structure(self):
        panes = [
            PaneSpec(name="repo-a", command="cmd-a", working_dir="/root/projects/ws/repo-a"),
            PaneSpec(name="repo-b", command="cmd-b", working_dir="/root/projects/ws/repo-b"),
        ]
        cmds = build_tmux_commands("my-container", "my-session", panes)

        # First cmd: kill-session
        assert cmds[0] == [
            "docker",
            "exec",
            "my-container",
            "tmux",
            "kill-session",
            "-t",
            "my-session",
        ]

        # Second cmd: new-session
        assert "new-session" in cmds[1]
        assert "-d" in cmds[1]
        assert "-s" in cmds[1]

        # Should have exactly 1 split-window (for the second pane)
        split_cmds = [c for c in cmds if "split-window" in c]
        assert len(split_cmds) == 1

        # Layout should be even-vertical for 2 panes
        layout_cmds = [c for c in cmds if "select-layout" in c]
        assert len(layout_cmds) == 1
        assert "even-vertical" in layout_cmds[0]

        # Last command should be interactive attach
        assert cmds[-1] == [
            "docker",
            "exec",
            "-it",
            "my-container",
            "tmux",
            "attach-session",
            "-t",
            "my-session",
        ]

    def test_3_panes_uses_main_horizontal(self):
        panes = [
            PaneSpec(name=f"repo-{i}", command=f"cmd-{i}", working_dir=f"/d/{i}") for i in range(3)
        ]
        cmds = build_tmux_commands("container", "session", panes)

        layout_cmds = [c for c in cmds if "select-layout" in c]
        assert "main-horizontal" in layout_cmds[0]

        split_cmds = [c for c in cmds if "split-window" in c]
        assert len(split_cmds) == 2

    def test_4_panes_uses_tiled(self):
        panes = [
            PaneSpec(name=f"repo-{i}", command=f"cmd-{i}", working_dir=f"/d/{i}") for i in range(4)
        ]
        cmds = build_tmux_commands("container", "session", panes)

        layout_cmds = [c for c in cmds if "select-layout" in c]
        assert "tiled" in layout_cmds[0]

        split_cmds = [c for c in cmds if "split-window" in c]
        assert len(split_cmds) == 3

    def test_includes_session_options(self):
        panes = [
            PaneSpec(name="repo-a", command="cmd-a", working_dir="/d/a"),
            PaneSpec(name="repo-b", command="cmd-b", working_dir="/d/b"),
        ]
        cmds = build_tmux_commands("container", "session", panes)
        all_args = [" ".join(c) for c in cmds]
        joined = "\n".join(all_args)

        assert "mouse" in joined
        assert "pane-border-status" in joined
        assert "escape-time" in joined
        assert "focus-events" in joined
        assert "pane-border-lines" in joined
        assert "pane-border-indicators" in joined

    def test_red_active_green_inactive_borders(self):
        panes = [
            PaneSpec(name="repo-a", command="cmd-a", working_dir="/d/a"),
            PaneSpec(name="repo-b", command="cmd-b", working_dir="/d/b"),
        ]
        cmds = build_tmux_commands("container", "session", panes)
        all_args = [" ".join(c) for c in cmds]
        joined = "\n".join(all_args)

        # Active = red (colour196), inactive = green (colour34)
        assert "colour196" in joined
        assert "colour34" in joined

    def test_status_bar_has_help_hints(self):
        panes = [
            PaneSpec(name="repo-a", command="cmd-a", working_dir="/d/a"),
            PaneSpec(name="repo-b", command="cmd-b", working_dir="/d/b"),
        ]
        cmds = build_tmux_commands("container", "session", panes)
        all_args = [" ".join(c) for c in cmds]
        joined = "\n".join(all_args)

        assert "C-b z=zoom" in joined
        assert "C-b d=detach" in joined

    def test_server_level_terminal_options(self):
        panes = [
            PaneSpec(name="repo-a", command="cmd-a", working_dir="/d/a"),
            PaneSpec(name="repo-b", command="cmd-b", working_dir="/d/b"),
        ]
        cmds = build_tmux_commands("container", "session", panes)

        # Find server-level options (use -s or -sa, NOT -t session_name)
        default_term_cmds = [
            c for c in cmds if "default-terminal" in c and "-s" in c and "session" not in c
        ]
        assert len(default_term_cmds) == 1
        assert "tmux-256color" in default_term_cmds[0]

        term_override_cmds = [c for c in cmds if "terminal-overrides" in c and "-sa" in c]
        assert len(term_override_cmds) == 1

    def test_pane_titles_set(self):
        panes = [
            PaneSpec(name="alpha", command="cmd-a", working_dir="/d/a"),
            PaneSpec(name="beta", command="cmd-b", working_dir="/d/b"),
        ]
        cmds = build_tmux_commands("container", "session", panes)

        # Find select-pane commands with -T flag (title)
        title_cmds = [c for c in cmds if "select-pane" in c and "-T" in c]
        assert len(title_cmds) == 2
        assert "alpha" in title_cmds[0]
        assert "beta" in title_cmds[1]

    def test_send_keys_for_each_pane(self):
        panes = [
            PaneSpec(name="repo-a", command="cmd-a", working_dir="/d/a"),
            PaneSpec(name="repo-b", command="cmd-b", working_dir="/d/b"),
        ]
        cmds = build_tmux_commands("container", "session", panes)

        send_cmds = [c for c in cmds if "send-keys" in c]
        assert len(send_cmds) == 2
        assert "cmd-a" in send_cmds[0]
        assert "cmd-b" in send_cmds[1]


# ── Selector tests ──────────────────────────────────────────────────


class TestSelectionItem:
    def test_construction(self):
        item = SelectionItem(label="My Repo", value="./my-repo", description="service")
        assert item.label == "My Repo"
        assert item.value == "./my-repo"
        assert item.description == "service"

    def test_default_description(self):
        item = SelectionItem(label="My Repo", value="./my-repo")
        assert item.description == ""


class TestInteractiveSelectNotTTY:
    @patch("ai_shell.selector.sys")
    def test_raises_when_not_tty(self, mock_sys):
        from ai_shell.selector import interactive_multi_select

        mock_sys.stdin.isatty.return_value = False
        items = [SelectionItem(label="repo", value=".")]

        with pytest.raises(click.ClickException, match="--multi requires an interactive terminal"):
            interactive_multi_select(items)


class TestRichFallbackSelector:
    """Tests for the Rich-based numbered-prompt fallback (Windows path)."""

    @patch("ai_shell.selector._CURSES_AVAILABLE", False)
    @patch("ai_shell.selector.sys")
    @patch("rich.console.Console")
    def test_returns_correct_items(self, mock_console_cls, mock_sys):
        from ai_shell.selector import interactive_multi_select

        mock_sys.stdin.isatty.return_value = True
        items = [
            SelectionItem(label="repo-a", value="./repo-a", description="service"),
            SelectionItem(label="repo-b", value="./repo-b", description="library"),
            SelectionItem(label="repo-c", value="./repo-c"),
        ]

        mock_console = MagicMock()
        mock_console_cls.return_value = mock_console
        mock_console.input.return_value = "1,3"

        result = interactive_multi_select(items)

        assert len(result) == 2
        assert result[0].label == "repo-a"
        assert result[1].label == "repo-c"

    @patch("ai_shell.selector._CURSES_AVAILABLE", False)
    @patch("ai_shell.selector.sys")
    @patch("rich.console.Console")
    def test_cancel_with_q(self, mock_console_cls, mock_sys):
        from ai_shell.selector import interactive_multi_select

        mock_sys.stdin.isatty.return_value = True
        items = [SelectionItem(label="repo-a", value="./repo-a")]

        mock_console = MagicMock()
        mock_console_cls.return_value = mock_console
        mock_console.input.return_value = "q"

        result = interactive_multi_select(items)

        assert result == []

    @patch("ai_shell.selector._CURSES_AVAILABLE", False)
    @patch("ai_shell.selector.sys")
    @patch("rich.console.Console")
    def test_cancel_with_empty_input(self, mock_console_cls, mock_sys):
        from ai_shell.selector import interactive_multi_select

        mock_sys.stdin.isatty.return_value = True
        items = [SelectionItem(label="repo-a", value="./repo-a")]

        mock_console = MagicMock()
        mock_console_cls.return_value = mock_console
        mock_console.input.return_value = ""

        result = interactive_multi_select(items)

        assert result == []

    @patch("ai_shell.selector._CURSES_AVAILABLE", False)
    @patch("ai_shell.selector.sys")
    @patch("rich.console.Console")
    def test_validates_out_of_range(self, mock_console_cls, mock_sys):
        from ai_shell.selector import interactive_multi_select

        mock_sys.stdin.isatty.return_value = True
        items = [
            SelectionItem(label="repo-a", value="./repo-a"),
            SelectionItem(label="repo-b", value="./repo-b"),
        ]

        mock_console = MagicMock()
        mock_console_cls.return_value = mock_console
        # First call: out of range, second call: valid
        mock_console.input.side_effect = ["5", "1,2"]

        result = interactive_multi_select(items)

        assert len(result) == 2

    @patch("ai_shell.selector._CURSES_AVAILABLE", False)
    @patch("ai_shell.selector.sys")
    @patch("rich.console.Console")
    def test_validates_max_selections(self, mock_console_cls, mock_sys):
        from ai_shell.selector import interactive_multi_select

        mock_sys.stdin.isatty.return_value = True
        items = [SelectionItem(label=f"repo-{i}", value=f"./repo-{i}") for i in range(5)]

        mock_console = MagicMock()
        mock_console_cls.return_value = mock_console
        # First call: 5 selections (over max 4), second call: valid
        mock_console.input.side_effect = ["1,2,3,4,5", "1,2"]

        result = interactive_multi_select(items, max_selections=4)

        assert len(result) == 2

    @patch("ai_shell.selector._CURSES_AVAILABLE", False)
    @patch("ai_shell.selector.sys")
    @patch("rich.console.Console")
    def test_handles_keyboard_interrupt(self, mock_console_cls, mock_sys):
        from ai_shell.selector import interactive_multi_select

        mock_sys.stdin.isatty.return_value = True
        items = [SelectionItem(label="repo-a", value="./repo-a")]

        mock_console = MagicMock()
        mock_console_cls.return_value = mock_console
        mock_console.input.side_effect = KeyboardInterrupt

        result = interactive_multi_select(items)

        assert result == []


# ── CLI integration tests ───────────────────────────────────────────


WORKSPACE_YAML = """\
workspace:
  name: test-workspace
  repos_dir: "."

repos:
  - name: repo-a
    path: ./repo-a
    repo_type: service
  - name: repo-b
    path: ./repo-b
    repo_type: library
"""


class TestClaudeMultiCLI:
    def setup_method(self):
        self.runner = CliRunner()

    @patch("ai_shell.cli.commands.tools._check_bedrock_access")
    @patch("ai_shell.cli.commands.tools.build_dev_environment")
    @patch("ai_shell.cli.commands.tools.ContainerManager")
    @patch("ai_shell.cli.commands.tools.load_config")
    def test_multi_no_workspace_yaml(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        """--multi without workspace.yaml gives a clear error."""
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(cli, ["claude", "--multi"])

        assert result.exit_code != 0
        assert "No workspace.yaml found" in result.output

    @patch("ai_shell.cli.commands.tools._check_bedrock_access")
    @patch("ai_shell.cli.commands.tools.build_dev_environment")
    @patch("ai_shell.cli.commands.tools.ContainerManager")
    @patch("ai_shell.cli.commands.tools.load_config")
    def test_multi_incompatible_with_init(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        result = self.runner.invoke(cli, ["claude", "--multi", "--init"])
        assert result.exit_code != 0
        assert "--multi is incompatible" in result.output

    @patch("ai_shell.cli.commands.tools._check_bedrock_access")
    @patch("ai_shell.cli.commands.tools.build_dev_environment")
    @patch("ai_shell.cli.commands.tools.ContainerManager")
    @patch("ai_shell.cli.commands.tools.load_config")
    def test_multi_incompatible_with_worktree(
        self, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        result = self.runner.invoke(cli, ["claude", "--multi", "--worktree", "feat-1"])
        assert result.exit_code != 0
        assert "--multi is incompatible" in result.output

    @patch("ai_shell.cli.commands.tools._check_bedrock_access")
    @patch("ai_shell.cli.commands.tools.build_dev_environment")
    @patch("ai_shell.cli.commands.tools.ContainerManager")
    @patch("ai_shell.cli.commands.tools.load_config")
    @patch("ai_shell.selector.interactive_multi_select")
    def test_multi_zero_selections_aborts(
        self, mock_select, mock_config, mock_manager_cls, mock_build_env, mock_check_bedrock
    ):
        """Cancelling the selector exits cleanly."""
        mock_select.return_value = []

        with self.runner.isolated_filesystem():
            with open("workspace.yaml", "w") as f:
                f.write(WORKSPACE_YAML)

            result = self.runner.invoke(cli, ["claude", "--multi"])

        assert result.exit_code == 0
        assert "No repos selected" in result.output
        mock_manager_cls.assert_not_called()

    @patch("ai_shell.cli.commands.tools.subprocess.run")
    @patch("ai_shell.cli.commands.tools._check_bedrock_access")
    @patch("ai_shell.cli.commands.tools.build_dev_environment")
    @patch("ai_shell.cli.commands.tools.ContainerManager")
    @patch("ai_shell.cli.commands.tools.load_config")
    @patch("ai_shell.selector.interactive_multi_select")
    def test_multi_calls_tmux_commands(
        self,
        mock_select,
        mock_config,
        mock_manager_cls,
        mock_build_env,
        mock_check_bedrock,
        mock_subprocess,
    ):
        """Selecting 2 repos builds and runs tmux commands."""
        config = MagicMock()
        config.project_name = "test-workspace"
        config.claude_provider = ""
        config.bedrock_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = MagicMock()
        mock_config.return_value = config

        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager_cls.return_value = mock_manager

        mock_select.return_value = [
            SelectionItem(label="repo-a", value="./repo-a", description="service"),
            SelectionItem(label="repo-b", value="./repo-b", description="library"),
        ]

        # subprocess.run returns success for setup, then sys.exit for attach
        mock_subprocess.return_value = MagicMock(returncode=0)

        with self.runner.isolated_filesystem():
            with open("workspace.yaml", "w") as f:
                f.write(WORKSPACE_YAML)
            # Create the repo directories so validation passes
            import os

            os.makedirs("repo-a")
            os.makedirs("repo-b")

            self.runner.invoke(cli, ["claude", "--multi"])

        # Verify subprocess.run was called multiple times (tmux setup + attach)
        assert mock_subprocess.call_count > 1

        # Last call should be the interactive attach
        last_call_args = mock_subprocess.call_args_list[-1][0][0]
        assert "attach-session" in last_call_args
        assert "-it" in last_call_args

    @patch("ai_shell.cli.commands.tools.subprocess.run")
    @patch("ai_shell.cli.commands.tools._check_bedrock_access")
    @patch("ai_shell.cli.commands.tools.build_dev_environment")
    @patch("ai_shell.cli.commands.tools.ContainerManager")
    @patch("ai_shell.cli.commands.tools.load_config")
    @patch("ai_shell.selector.interactive_multi_select")
    def test_multi_safe_flag_propagates(
        self,
        mock_select,
        mock_config,
        mock_manager_cls,
        mock_build_env,
        mock_check_bedrock,
        mock_subprocess,
    ):
        """--safe omits --dangerously-skip-permissions from pane commands."""
        config = MagicMock()
        config.project_name = "test-workspace"
        config.claude_provider = ""
        config.bedrock_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = MagicMock()
        mock_config.return_value = config

        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager_cls.return_value = mock_manager

        mock_select.return_value = [
            SelectionItem(label="repo-a", value="./repo-a", description="service"),
            SelectionItem(label="repo-b", value="./repo-b", description="library"),
        ]

        mock_subprocess.return_value = MagicMock(returncode=0)

        with self.runner.isolated_filesystem():
            with open("workspace.yaml", "w") as f:
                f.write(WORKSPACE_YAML)
            import os

            os.makedirs("repo-a")
            os.makedirs("repo-b")

            self.runner.invoke(cli, ["claude", "--multi", "--safe"])

        # Find the send-keys calls to verify pane commands
        send_keys_calls = [
            call
            for call in mock_subprocess.call_args_list
            if any("send-keys" in str(a) for a in call[0])
        ]
        for call in send_keys_calls:
            cmd_str = " ".join(str(a) for a in call[0][0])
            assert "--dangerously-skip-permissions" not in cmd_str

    @patch("ai_shell.cli.commands.tools._check_bedrock_access")
    @patch("ai_shell.cli.commands.tools.build_dev_environment")
    @patch("ai_shell.cli.commands.tools.ContainerManager")
    @patch("ai_shell.cli.commands.tools.load_config")
    @patch("ai_shell.selector.interactive_multi_select")
    def test_multi_single_selection_uses_normal_flow(
        self,
        mock_select,
        mock_config,
        mock_manager_cls,
        mock_build_env,
        mock_check_bedrock,
    ):
        """Single selection falls back to normal Claude launch (no tmux)."""
        config = MagicMock()
        config.project_name = "repo-a"
        config.claude_provider = ""
        config.bedrock_profile = ""
        config.ai_profile = ""
        config.aws_region = ""
        config.extra_env = {}
        config.project_dir = MagicMock()
        mock_config.return_value = config

        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "augint-shell-test-dev"
        mock_manager.run_interactive.return_value = (0, 30.0)
        mock_manager_cls.return_value = mock_manager

        mock_select.return_value = [
            SelectionItem(label="repo-a", value="./repo-a", description="service"),
        ]

        with self.runner.isolated_filesystem():
            with open("workspace.yaml", "w") as f:
                f.write(WORKSPACE_YAML)
            import os

            os.makedirs("repo-a")

            self.runner.invoke(cli, ["claude", "--multi"])

        # Should use normal run_interactive flow, not subprocess for tmux
        mock_manager.run_interactive.assert_called_once()
        cmd = mock_manager.run_interactive.call_args[0][1]
        assert "claude" in cmd
        assert "--dangerously-skip-permissions" in cmd

    @patch("ai_shell.cli.commands.tools._check_bedrock_access")
    @patch("ai_shell.cli.commands.tools.build_dev_environment")
    @patch("ai_shell.cli.commands.tools.ContainerManager")
    @patch("ai_shell.cli.commands.tools.load_config")
    @patch("ai_shell.selector.interactive_multi_select")
    def test_multi_missing_repo_dir_raises(
        self,
        mock_select,
        mock_config,
        mock_manager_cls,
        mock_build_env,
        mock_check_bedrock,
    ):
        """Missing repo directories produce a clear error."""
        mock_select.return_value = [
            SelectionItem(label="repo-a", value="./repo-a", description="service"),
            SelectionItem(label="repo-b", value="./repo-b", description="library"),
        ]

        with self.runner.isolated_filesystem():
            with open("workspace.yaml", "w") as f:
                f.write(WORKSPACE_YAML)
            # Don't create the repo directories

            result = self.runner.invoke(cli, ["claude", "--multi"])

        assert result.exit_code != 0
        assert "not found" in result.output


# ── Defaults UV isolation test ──────────────────────────────────────


class TestBuildDevEnvironmentProjectName:
    def test_project_name_sets_uv_env(self):
        from ai_shell.defaults import build_dev_environment

        env = build_dev_environment(project_name="my-project")
        assert env["UV_PROJECT_ENVIRONMENT"] == "/root/.cache/uv/venvs/my-project"

    def test_no_project_name_no_uv_env(self):
        from ai_shell.defaults import build_dev_environment

        env = build_dev_environment()
        assert "UV_PROJECT_ENVIRONMENT" not in env

    def test_empty_project_name_no_uv_env(self):
        from ai_shell.defaults import build_dev_environment

        env = build_dev_environment(project_name="")
        assert "UV_PROJECT_ENVIRONMENT" not in env


# ── Workspace YAML parser test ──────────────────────────────────────


class TestLoadWorkspaceRepos:
    def test_parses_workspace_yaml(self, tmp_path):
        from ai_shell.cli.commands.tools import _load_workspace_repos

        yaml_path = tmp_path / "workspace.yaml"
        yaml_path.write_text(WORKSPACE_YAML)

        name, repos = _load_workspace_repos(yaml_path)

        assert name == "test-workspace"
        assert len(repos) == 2
        assert repos[0]["name"] == "repo-a"
        assert repos[1]["name"] == "repo-b"

    def test_invalid_yaml_raises(self, tmp_path):
        from ai_shell.cli.commands.tools import _load_workspace_repos

        yaml_path = tmp_path / "workspace.yaml"
        yaml_path.write_text("{{invalid yaml")

        with pytest.raises(click.ClickException, match="Failed to parse"):
            _load_workspace_repos(yaml_path)
