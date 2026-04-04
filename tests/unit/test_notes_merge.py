"""Tests for ai_shell.notes_merge module."""

from unittest.mock import patch

from ai_shell.notes_merge import merge_notes_into_context


class TestMergeNotesIntoContext:
    def test_unsupported_tool_returns_false(self, tmp_path):
        assert merge_notes_into_context(tmp_path, "aider") is False

    def test_skipped_when_context_file_missing(self, tmp_path):
        """No CLAUDE.md -> skip merge, return False."""
        with patch("ai_shell.notes_merge.subprocess") as mock_sub:
            result = merge_notes_into_context(tmp_path, "claude")
        assert result is False
        mock_sub.run.assert_not_called()

    def test_skipped_when_binary_not_found(self, tmp_path):
        """CLAUDE.md exists but claude not on PATH."""
        (tmp_path / "CLAUDE.md").write_text("# Project")
        with patch("ai_shell.notes_merge.shutil.which", return_value=None):
            result = merge_notes_into_context(tmp_path, "claude")
        assert result is False

    def test_claude_merge_correct_command(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Project")
        with (
            patch("ai_shell.notes_merge.shutil.which", return_value="/usr/bin/claude"),
            patch("ai_shell.notes_merge.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            result = merge_notes_into_context(tmp_path, "claude")

        assert result is True
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "--dangerously-skip-permissions" in cmd
        assert mock_run.call_args[1]["cwd"] == tmp_path

    def test_codex_merge_correct_command(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("# Agents")
        with (
            patch("ai_shell.notes_merge.shutil.which", return_value="/usr/bin/codex"),
            patch("ai_shell.notes_merge.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            result = merge_notes_into_context(tmp_path, "codex")

        assert result is True
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "codex"
        assert "exec" in cmd
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd

    def test_opencode_uses_codex_binary(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("# Agents")
        with (
            patch("ai_shell.notes_merge.shutil.which", return_value="/usr/bin/codex"),
            patch("ai_shell.notes_merge.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            result = merge_notes_into_context(tmp_path, "opencode")

        assert result is True
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "codex"

    def test_subprocess_failure_returns_false(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Project")
        with (
            patch("ai_shell.notes_merge.shutil.which", return_value="/usr/bin/claude"),
            patch("ai_shell.notes_merge.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 1
            result = merge_notes_into_context(tmp_path, "claude")

        assert result is False

    def test_subprocess_timeout_returns_false(self, tmp_path):
        import subprocess

        (tmp_path / "CLAUDE.md").write_text("# Project")
        with (
            patch("ai_shell.notes_merge.shutil.which", return_value="/usr/bin/claude"),
            patch("ai_shell.notes_merge.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["claude"], timeout=120)
            result = merge_notes_into_context(tmp_path, "claude")

        assert result is False

    def test_prompt_contains_template_content(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Project")
        with (
            patch("ai_shell.notes_merge.shutil.which", return_value="/usr/bin/claude"),
            patch("ai_shell.notes_merge.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            merge_notes_into_context(tmp_path, "claude")

        cmd = mock_run.call_args[0][0]
        prompt = cmd[cmd.index("-p") + 1]
        assert "into CLAUDE.md" in prompt
        assert "Critical Rules" in prompt
        assert "No rebase on main" in prompt

    def test_codex_prompt_references_agents_md(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("# Agents")
        with (
            patch("ai_shell.notes_merge.shutil.which", return_value="/usr/bin/codex"),
            patch("ai_shell.notes_merge.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            merge_notes_into_context(tmp_path, "codex")

        cmd = mock_run.call_args[0][0]
        # For codex exec, prompt is the last positional arg
        prompt = cmd[-1]
        assert "into AGENTS.md" in prompt

    def test_background_uses_popen(self, tmp_path):
        """background=True should use Popen, not run."""
        (tmp_path / "CLAUDE.md").write_text("# Project")
        with (
            patch("ai_shell.notes_merge.shutil.which", return_value="/usr/bin/claude"),
            patch("ai_shell.notes_merge.subprocess.Popen") as mock_popen,
            patch("ai_shell.notes_merge.subprocess.run") as mock_run,
        ):
            result = merge_notes_into_context(tmp_path, "claude", background=True)

        assert result is True
        mock_popen.assert_called_once()
        mock_run.assert_not_called()
        call_kwargs = mock_popen.call_args[1]
        from subprocess import DEVNULL

        assert call_kwargs["stdout"] is DEVNULL
        assert call_kwargs["stderr"] is DEVNULL
        assert call_kwargs["cwd"] == tmp_path

    def test_background_skips_when_context_file_missing(self, tmp_path):
        """background=True still returns False if context file is missing."""
        with patch("ai_shell.notes_merge.subprocess.Popen") as mock_popen:
            result = merge_notes_into_context(tmp_path, "claude", background=True)
        assert result is False
        mock_popen.assert_not_called()

    def test_background_skips_when_binary_missing(self, tmp_path):
        """background=True still returns False if binary not on PATH."""
        (tmp_path / "CLAUDE.md").write_text("# Project")
        with (
            patch("ai_shell.notes_merge.shutil.which", return_value=None),
            patch("ai_shell.notes_merge.subprocess.Popen") as mock_popen,
        ):
            result = merge_notes_into_context(tmp_path, "claude", background=True)
        assert result is False
        mock_popen.assert_not_called()
