"""Tests for the interactive multi-pane wizard and pane builder."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import click
from click.testing import CliRunner

from ai_shell.cli.__main__ import cli
from ai_shell.interactive import (
    InteractiveConfig,
    PaneChoice,
    PaneType,
    _build_pane_options,
    build_interactive_panes,
    run_interactive_wizard,
)

# ── Test data ────────────────────────────────────────────────────────

SAMPLE_WORKSPACE_REPOS = [
    {"name": "repo-a", "path": "./repo-a", "repo_type": "service"},
    {"name": "repo-b", "path": "./repo-b", "repo_type": "library"},
]

TEST_EXEC_ENV = {
    "AWS_PROFILE": "",
    "AWS_REGION": "us-east-1",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_PAGER": "",
    "GH_TOKEN": "test-token",
    "GITHUB_TOKEN": "test-token",
    "IS_SANDBOX": "1",
}

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


def _no_existing_session(*args, **kwargs):
    """subprocess.run side_effect: session check returns 1, everything else 0."""
    result = MagicMock()
    cmd = args[0] if args else kwargs.get("args", [])
    if isinstance(cmd, list) and "has-session" in cmd:
        result.returncode = 1
    else:
        result.returncode = 0
    return result


def _make_config_mock(project_name="test-project"):
    config = MagicMock()
    config.project_name = project_name
    config.claude_provider = ""
    config.bedrock_profile = ""
    config.ai_profile = ""
    config.aws_region = ""
    config.extra_env = {}
    config.project_dir = MagicMock()
    config.local_chrome = False
    return config


# ── _build_pane_options ──────────────────────────────────────────────


class TestBuildPaneOptions:
    def test_no_workspace_repos(self):
        options = _build_pane_options("my-project", None)
        assert len(options) == 2
        assert options[0].pane_type == PaneType.THIS_PROJECT
        assert "my-project" in options[0].label
        assert options[1].pane_type == PaneType.BASH

    def test_empty_workspace_repos(self):
        options = _build_pane_options("my-project", [])
        assert len(options) == 2

    def test_with_workspace_repos(self):
        options = _build_pane_options("my-project", SAMPLE_WORKSPACE_REPOS)
        assert len(options) == 4
        assert options[0].pane_type == PaneType.THIS_PROJECT
        assert options[1].pane_type == PaneType.BASH
        assert options[2].pane_type == PaneType.WORKSPACE_REPO
        assert options[2].repo_name == "repo-a"
        assert options[2].repo_path == "./repo-a"
        assert options[3].pane_type == PaneType.WORKSPACE_REPO
        assert options[3].repo_name == "repo-b"

    def test_workspace_repo_labels_include_type(self):
        options = _build_pane_options("my-project", SAMPLE_WORKSPACE_REPOS)
        assert "service" in options[2].label
        assert "library" in options[3].label

    def test_workspace_repo_without_type(self):
        repos = [{"name": "plain-repo", "path": "./plain-repo"}]
        options = _build_pane_options("my-project", repos)
        assert options[2].label == "plain-repo"


# ── run_interactive_wizard ───────────────────────────────────────────


class TestRunInteractiveWizard:
    def test_basic_two_worktree_panes(self):
        # 2 windows, both "This project", no teams, no chrome
        with patch("ai_shell.interactive.click") as mock_click:
            mock_click.prompt.side_effect = [2, 1, 1]
            mock_click.confirm.side_effect = [False, False]
            mock_click.IntRange = click.IntRange
            mock_click.Abort = click.Abort

            result = run_interactive_wizard(project_name="my-project")

        assert result is not None
        assert len(result.pane_choices) == 2
        assert all(c.pane_type == PaneType.THIS_PROJECT for c in result.pane_choices)
        assert result.team_mode is False
        assert result.shared_chrome is False

    def test_mixed_panes_with_workspace(self):
        # 3 windows: This project, Bash, repo-a
        with patch("ai_shell.interactive.click") as mock_click:
            mock_click.prompt.side_effect = [3, 1, 2, 3]
            mock_click.confirm.side_effect = [True, True]
            mock_click.IntRange = click.IntRange
            mock_click.Abort = click.Abort

            result = run_interactive_wizard(
                project_name="my-project",
                workspace_repos=SAMPLE_WORKSPACE_REPOS,
            )

        assert result is not None
        assert len(result.pane_choices) == 3
        assert result.pane_choices[0].pane_type == PaneType.THIS_PROJECT
        assert result.pane_choices[1].pane_type == PaneType.BASH
        assert result.pane_choices[2].pane_type == PaneType.WORKSPACE_REPO
        assert result.pane_choices[2].repo_name == "repo-a"
        assert result.team_mode is True
        assert result.shared_chrome is True

    def test_cancel_returns_none(self):
        with patch("ai_shell.interactive.click") as mock_click:
            mock_click.prompt.side_effect = KeyboardInterrupt
            mock_click.Abort = click.Abort

            result = run_interactive_wizard(project_name="my-project")

        assert result is None

    def test_eof_returns_none(self):
        with patch("ai_shell.interactive.click") as mock_click:
            mock_click.prompt.side_effect = EOFError
            mock_click.Abort = click.Abort

            result = run_interactive_wizard(project_name="my-project")

        assert result is None


# ── build_interactive_panes ──────────────────────────────────────────


class TestBuildInteractivePanes:
    def _mock_worktree(self, container_name, project_dir, wt_name):
        return f"{project_dir}/.claude/worktrees/{wt_name}"

    def test_this_project_creates_worktree_pane(self):
        config = InteractiveConfig(
            pane_choices=[PaneChoice(pane_type=PaneType.THIS_PROJECT)],
        )
        panes = build_interactive_panes(
            config=config,
            project_name="my-project",
            container_name="test-container",
            container_project_root="/root/projects/my-project",
            safe=False,
            extra_args=(),
            setup_worktree_fn=self._mock_worktree,
        )

        assert len(panes) == 1
        assert "my-project-wt-" in panes[0].name
        assert ".claude/worktrees/" in panes[0].working_dir
        assert "claude" in panes[0].command
        assert "--dangerously-skip-permissions" in panes[0].command

    def test_bash_pane(self):
        config = InteractiveConfig(
            pane_choices=[PaneChoice(pane_type=PaneType.BASH)],
        )
        panes = build_interactive_panes(
            config=config,
            project_name="my-project",
            container_name="test-container",
            container_project_root="/root/projects/my-project",
            safe=False,
            extra_args=(),
            setup_worktree_fn=self._mock_worktree,
        )

        assert len(panes) == 1
        assert panes[0].name == "bash-1"
        assert panes[0].command == "/bin/bash"
        assert panes[0].working_dir == "/root/projects/my-project"

    def test_multiple_bash_panes_get_numbered(self):
        config = InteractiveConfig(
            pane_choices=[
                PaneChoice(pane_type=PaneType.BASH),
                PaneChoice(pane_type=PaneType.BASH),
            ],
        )
        panes = build_interactive_panes(
            config=config,
            project_name="my-project",
            container_name="test-container",
            container_project_root="/root/projects/my-project",
            safe=False,
            extra_args=(),
            setup_worktree_fn=self._mock_worktree,
        )

        assert panes[0].name == "bash-1"
        assert panes[1].name == "bash-2"

    def test_workspace_repo_pane(self):
        config = InteractiveConfig(
            pane_choices=[
                PaneChoice(
                    pane_type=PaneType.WORKSPACE_REPO,
                    repo_name="repo-a",
                    repo_path="./repo-a",
                ),
            ],
        )
        panes = build_interactive_panes(
            config=config,
            project_name="my-workspace",
            container_name="test-container",
            container_project_root="/root/projects/my-workspace",
            safe=False,
            extra_args=(),
            setup_worktree_fn=self._mock_worktree,
        )

        assert len(panes) == 1
        assert panes[0].name == "repo-a"
        assert panes[0].working_dir == "/root/projects/my-workspace/repo-a"
        assert "claude" in panes[0].command

    def test_team_mode_only_on_first_claude_pane(self):
        config = InteractiveConfig(
            pane_choices=[
                PaneChoice(pane_type=PaneType.BASH),
                PaneChoice(pane_type=PaneType.THIS_PROJECT),
                PaneChoice(
                    pane_type=PaneType.WORKSPACE_REPO,
                    repo_name="repo-a",
                    repo_path="./repo-a",
                ),
            ],
            team_mode=True,
        )
        panes = build_interactive_panes(
            config=config,
            project_name="my-project",
            container_name="test-container",
            container_project_root="/root/projects/my-project",
            safe=False,
            extra_args=(),
            setup_worktree_fn=self._mock_worktree,
        )

        # Bash pane should have no team env
        assert "AGENT_TEAMS" not in panes[0].command

        # First Claude pane (THIS_PROJECT) should have team env
        assert "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1" in panes[1].command

        # Second Claude pane (WORKSPACE_REPO) should NOT have team env
        assert "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" not in panes[2].command

    def test_shared_chrome_adds_mcp_to_all_claude_panes(self):
        config = InteractiveConfig(
            pane_choices=[
                PaneChoice(pane_type=PaneType.THIS_PROJECT),
                PaneChoice(pane_type=PaneType.BASH),
                PaneChoice(
                    pane_type=PaneType.WORKSPACE_REPO,
                    repo_name="repo-a",
                    repo_path="./repo-a",
                ),
            ],
            shared_chrome=True,
        )
        mcp_path = "/etc/ai-shell/chrome-mcp.json"
        panes = build_interactive_panes(
            config=config,
            project_name="my-project",
            container_name="test-container",
            container_project_root="/root/projects/my-project",
            safe=False,
            extra_args=(),
            mcp_config_path=mcp_path,
            setup_worktree_fn=self._mock_worktree,
        )

        # Claude panes should have MCP config
        assert "--mcp-config" in panes[0].command
        assert mcp_path in panes[0].command
        assert "--mcp-config" in panes[2].command

        # Bash pane should not
        assert "--mcp-config" not in panes[1].command

    def test_safe_mode_propagated(self):
        config = InteractiveConfig(
            pane_choices=[PaneChoice(pane_type=PaneType.THIS_PROJECT)],
        )
        panes = build_interactive_panes(
            config=config,
            project_name="my-project",
            container_name="test-container",
            container_project_root="/root/projects/my-project",
            safe=True,
            extra_args=(),
            setup_worktree_fn=self._mock_worktree,
        )

        assert "--dangerously-skip-permissions" not in panes[0].command
        assert "||" not in panes[0].command

    def test_no_chrome_no_mcp_args(self):
        config = InteractiveConfig(
            pane_choices=[PaneChoice(pane_type=PaneType.THIS_PROJECT)],
            shared_chrome=False,
        )
        panes = build_interactive_panes(
            config=config,
            project_name="my-project",
            container_name="test-container",
            container_project_root="/root/projects/my-project",
            safe=False,
            extra_args=(),
            mcp_config_path="/etc/ai-shell/chrome-mcp.json",
            setup_worktree_fn=self._mock_worktree,
        )

        # shared_chrome=False means mcp_config_path should not be passed through
        assert "--mcp-config" not in panes[0].command


# ── CLI integration ──────────────────────────────────────────────────


class TestInteractiveCLI:
    def setup_method(self):
        self.runner = CliRunner()

    def test_interactive_requires_multi(self):
        result = self.runner.invoke(cli, ["claude", "--interactive"])
        assert result.exit_code != 0
        assert "--interactive requires --multi" in result.output

    def test_interactive_conflicts_with_team(self):
        result = self.runner.invoke(cli, ["claude", "--multi", "--interactive", "--team"])
        assert result.exit_code != 0
        assert "incompatible" in result.output

    def test_interactive_conflicts_with_local_chrome(self):
        result = self.runner.invoke(cli, ["claude", "--multi", "--interactive", "--local-chrome"])
        assert result.exit_code != 0
        assert "incompatible" in result.output

    @patch("ai_shell.cli.commands.tools.subprocess.run")
    @patch("ai_shell.cli.commands.tools.dev_container_name", return_value="test-container")
    @patch("ai_shell.cli.commands.tools._check_bedrock_access")
    @patch("ai_shell.cli.commands.tools.build_dev_environment")
    @patch("ai_shell.cli.commands.tools.ContainerManager")
    @patch("ai_shell.cli.commands.tools.load_config")
    def test_interactive_multi_launches_wizard(
        self,
        mock_config,
        mock_manager_cls,
        mock_build_env,
        mock_check_bedrock,
        mock_dev_name,
        mock_subprocess,
    ):
        """--multi --interactive runs the wizard and launches tmux."""
        mock_config.return_value = _make_config_mock()
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "test-container"
        mock_manager_cls.return_value = mock_manager
        mock_subprocess.side_effect = _no_existing_session

        with self.runner.isolated_filesystem():
            # 2 windows, both "This project", no teams, no chrome
            self.runner.invoke(
                cli,
                ["claude", "--multi", "--interactive"],
                input="2\n1\n1\nn\nn\n",
            )

        # Should have called tmux attach-session
        attach_calls = [
            call
            for call in mock_subprocess.call_args_list
            if any("attach-session" in str(a) for a in call[0])
        ]
        assert len(attach_calls) >= 1

    @patch("ai_shell.interactive.run_interactive_wizard", return_value=None)
    @patch("ai_shell.cli.commands.tools.subprocess.run")
    @patch("ai_shell.cli.commands.tools.dev_container_name", return_value="test-container")
    @patch("ai_shell.cli.commands.tools._check_bedrock_access")
    @patch("ai_shell.cli.commands.tools.build_dev_environment")
    @patch("ai_shell.cli.commands.tools.ContainerManager")
    @patch("ai_shell.cli.commands.tools.load_config")
    def test_interactive_cancel_exits_cleanly(
        self,
        mock_config,
        mock_manager_cls,
        mock_build_env,
        mock_check_bedrock,
        mock_dev_name,
        mock_subprocess,
        mock_wizard,
    ):
        """Cancelling the wizard exits without launching tmux."""
        mock_config.return_value = _make_config_mock()
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "test-container"
        mock_manager_cls.return_value = mock_manager
        mock_subprocess.side_effect = _no_existing_session

        with self.runner.isolated_filesystem():
            self.runner.invoke(
                cli,
                ["claude", "--multi", "--interactive"],
            )

        # Should NOT have tried tmux attach
        attach_calls = [
            call
            for call in mock_subprocess.call_args_list
            if any("attach-session" in str(a) for a in call[0])
        ]
        assert len(attach_calls) == 0

    @patch("ai_shell.cli.commands.tools.subprocess.run")
    @patch("ai_shell.cli.commands.tools.dev_container_name", return_value="test-container")
    @patch("ai_shell.cli.commands.tools._check_bedrock_access")
    @patch("ai_shell.cli.commands.tools.build_dev_environment")
    @patch("ai_shell.cli.commands.tools.ContainerManager")
    @patch("ai_shell.cli.commands.tools.load_config")
    def test_interactive_with_workspace_shows_repo_options(
        self,
        mock_config,
        mock_manager_cls,
        mock_build_env,
        mock_check_bedrock,
        mock_dev_name,
        mock_subprocess,
    ):
        """With workspace.yaml, subrepos appear as options."""
        mock_config.return_value = _make_config_mock()
        mock_build_env.return_value = dict(TEST_EXEC_ENV)
        mock_manager = MagicMock()
        mock_manager.ensure_dev_container.return_value = "test-container"
        mock_manager_cls.return_value = mock_manager
        mock_subprocess.side_effect = _no_existing_session

        with self.runner.isolated_filesystem():
            with open("workspace.yaml", "w") as f:
                f.write(WORKSPACE_YAML)

            # 2 windows: repo-a (option 3) and Bash (option 2), no teams, no chrome
            self.runner.invoke(
                cli,
                ["claude", "--multi", "--interactive"],
                input="2\n3\n2\nn\nn\n",
            )

        # tmux commands should have been issued
        tmux_calls = [
            call
            for call in mock_subprocess.call_args_list
            if any("tmux" in str(a) for a in call[0])
        ]
        assert len(tmux_calls) >= 1
