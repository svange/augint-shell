"""Unit tests for tmux split-pane workspace mode (--tmux) and cheat sheet."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from ai_shell.cli.__main__ import cli
from ai_shell.config import AiShellConfig, load_config
from ai_shell.tmux import TMUX_CHEATSHEET, build_tmux_workspace_cmd, sanitize_session_name


class TestTmuxBuilder:
    def test_sanitize_session_name(self) -> None:
        assert sanitize_session_name("ai-shell-claude") == "ai-shell-claude"
        assert sanitize_session_name("my.repo:name") == "my-repo-name"
        assert sanitize_session_name("...") == "ai-shell"

    def test_workspace_cmd_puts_nvim_left_and_agent_right(self) -> None:
        cmd = build_tmux_workspace_cmd(
            ["opencode", "--model", "foo"],
            session_name="ai-shell-opencode",
            agent_label="opencode",
        )
        assert cmd[:2] == ["bash", "-lc"]
        script = cmd[2]
        assert "tmux has-session -t ai-shell-opencode" in script
        assert "tmux attach-session -t ai-shell-opencode" in script
        assert "nvim; exec bash -l" in script
        assert "tmux split-window -h" in script
        assert "exec opencode --model foo" in script
        assert "-T nvim" in script
        assert "-T opencode" in script
        assert 'tmux select-pane -t "$RIGHT_PANE"' in script


class TestTmuxConfigAndCli:
    def test_config_yaml_and_env_var(self, tmp_path: Path) -> None:
        (tmp_path / ".ai-shell.yaml").write_text("container:\n  tmux: true\n", encoding="utf-8")
        with patch.dict("os.environ", {}, clear=True):
            cfg = load_config(project_dir=tmp_path)
        assert cfg.tmux is True

        with patch.dict("os.environ", {"AI_SHELL_TMUX": "0"}, clear=True):
            cfg2 = load_config(project_dir=tmp_path)
        assert cfg2.tmux is False

    def test_cli_tmux_prints_cheatsheet(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["tmux"])
        assert result.exit_code == 0
        assert "TMUX & AI-SHELL WORKSPACE" in result.output
        assert "ai-shell opencode --tmux" in result.output
        assert "ai-shell claude --tmux" in result.output
        assert TMUX_CHEATSHEET.strip() in result.output

    def test_cli_shell_tmux_wraps_command(self, tmp_path: Path) -> None:
        exec_calls: list[list[str]] = []

        def _fake_cm(_cfg: AiShellConfig) -> MagicMock:
            m = MagicMock()
            m.ensure_dev_container.return_value = "augint-shell-test-dev"
            m.get_dev_ports.return_value = {}
            m.exec_interactive.side_effect = lambda _n, cmd, **_kw: exec_calls.append(cmd)
            return m

        runner = CliRunner()
        with (
            patch("ai_shell.cli.commands.tools.ContainerManager", side_effect=_fake_cm),
            patch("ai_shell.cli.commands.tools.Path.cwd", return_value=tmp_path),
        ):
            result = runner.invoke(cli, ["shell", "--tmux"])
        assert result.exit_code == 0, result.output
        assert len(exec_calls) == 1
        assert exec_calls[0][:2] == ["bash", "-lc"]
        assert "nvim; exec bash -l" in exec_calls[0][2]
        assert "tmux split-window -h" in exec_calls[0][2]
        assert "/bin/bash -l" in exec_calls[0][2]

    def test_cli_claude_tmux_wraps_command(self, tmp_path: Path) -> None:
        exec_calls: list[list[str]] = []

        def _fake_cm(_cfg: AiShellConfig) -> MagicMock:
            m = MagicMock()
            m.ensure_dev_container.return_value = "augint-shell-test-dev"
            m.get_dev_ports.return_value = {}
            m.exec_interactive.side_effect = lambda _n, cmd, **_kw: exec_calls.append(cmd)
            return m

        runner = CliRunner()
        with (
            patch("ai_shell.cli.commands.tools.ContainerManager", side_effect=_fake_cm),
            patch("ai_shell.cli.commands.tools.Path.cwd", return_value=tmp_path),
        ):
            result = runner.invoke(cli, ["claude", "--tmux"])
        assert result.exit_code == 0, result.output
        assert len(exec_calls) == 1
        assert exec_calls[0][:2] == ["bash", "-lc"]
        assert "nvim; exec bash -l" in exec_calls[0][2]
        assert "claude --dangerously-skip-permissions -c" in exec_calls[0][2]
