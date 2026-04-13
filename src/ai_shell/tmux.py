"""Tmux session builder for multi-pane Claude Code sessions.

All public functions are pure -- they return command argument lists without
executing anything.  The caller (``tools.py``) is responsible for running
them via ``subprocess.run`` / ``os.execvp``.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

# ── Data ─────────────────────────────────────────────────────────────

TMUX_SESSION_PREFIX = "claude-multi"


@dataclass
class PaneSpec:
    """Specification for a single tmux pane."""

    name: str  # Display name (pane title)
    command: str  # Shell command to run in the pane
    working_dir: str  # Container-side absolute path


# ── Command builders ─────────────────────────────────────────────────


def build_claude_pane_command(
    *,
    repo_name: str,
    safe: bool = False,
    extra_args: tuple[str, ...] = (),
) -> str:
    """Build the claude invocation string for a single tmux pane.

    Runs directly inside the container.  Prefixes ``UV_PROJECT_ENVIRONMENT``
    so each repo gets an isolated virtualenv within the shared UV cache volume.
    Uses Claude Code's ``-n`` flag for session naming.
    """
    uv_env = f"UV_PROJECT_ENVIRONMENT=/root/.cache/uv/venvs/{repo_name}"
    parts: list[str] = ["claude"]
    if not safe:
        parts.append("--dangerously-skip-permissions")
        parts.append("-c")
    parts.extend(["-n", repo_name])
    if extra_args:
        parts.append("--")
        parts.extend(extra_args)
    cmd = " ".join(shlex.quote(p) for p in parts)
    return f"{uv_env} {cmd}"


def select_layout(pane_count: int) -> str:
    """Return the tmux layout name for the given pane count.

    2 panes: even-vertical   (top / bottom)
    3 panes: main-horizontal (1 large top, 2 split bottom)
    4 panes: tiled           (even quarters)
    """
    layouts = {
        2: "even-vertical",
        3: "main-horizontal",
        4: "tiled",
    }
    return layouts.get(pane_count, "tiled")


def build_tmux_commands(
    container_name: str,
    session_name: str,
    panes: list[PaneSpec],
) -> list[list[str]]:
    """Build the sequence of ``docker exec`` commands for the tmux session.

    Every command except the **last** is non-interactive (no ``-it``).
    The last command is an interactive ``docker exec -it ... tmux attach``
    intended to be executed via ``os.execvp`` to replace the current process.

    Returns a list of argument lists suitable for ``subprocess.run()``.
    """
    if not panes:
        return []

    cmds: list[list[str]] = []

    def _exec(*args: str) -> list[str]:
        return ["docker", "exec", container_name, *args]

    # 1. Kill stale session (ignore errors -- caller should use check=False)
    cmds.append(_exec("tmux", "kill-session", "-t", session_name))

    # 2. Create session with first pane
    first = panes[0]
    cmds.append(_exec("tmux", "new-session", "-d", "-s", session_name, "-c", first.working_dir))

    # 3. Split additional panes
    for pane in panes[1:]:
        cmds.append(
            _exec("tmux", "split-window", "-t", f"{session_name}:0", "-c", pane.working_dir)
        )

    # 4. Apply layout
    layout = select_layout(len(panes))
    cmds.append(_exec("tmux", "select-layout", "-t", f"{session_name}:0", layout))

    # 5. Set pane titles
    for i, pane in enumerate(panes):
        cmds.append(_exec("tmux", "select-pane", "-t", f"{session_name}:0.{i}", "-T", pane.name))

    # 6. Send commands to each pane
    for i, pane in enumerate(panes):
        cmds.append(
            _exec("tmux", "send-keys", "-t", f"{session_name}:0.{i}", pane.command, "Enter")
        )

    # 7. Configure session options -- red active / green inactive borders
    session_options: list[tuple[str, str]] = [
        # Mouse & responsiveness
        ("mouse", "on"),
        ("escape-time", "10"),
        ("history-limit", "50000"),
        ("focus-events", "on"),
        # Pane borders: red active, green inactive, heavy lines
        ("pane-border-status", "top"),
        ("pane-border-lines", "heavy"),
        (
            "pane-border-format",
            "#{?pane_active,#[fg=colour196 bold] #{pane_title} ,#[fg=colour34] #{pane_title} }",
        ),
        ("pane-border-style", "fg=colour34"),
        ("pane-active-border-style", "fg=colour196,bold"),
        ("pane-border-indicators", "arrows"),
        # Status bar
        ("status-style", "bg=colour235 fg=colour248"),
        ("status-left", "#[fg=colour196,bold] #S #[fg=colour248]| "),
        ("status-right", "#[fg=colour240] C-b z=zoom  C-b d=detach "),
        ("status-left-length", "40"),
        ("status-right-length", "40"),
    ]
    for key, value in session_options:
        cmds.append(_exec("tmux", "set-option", "-t", session_name, key, value))

    # 8. Server-level terminal options for true-color support
    cmds.append(_exec("tmux", "set-option", "-s", "default-terminal", "tmux-256color"))
    cmds.append(_exec("tmux", "set-option", "-sa", "terminal-overrides", ",xterm*:Tc"))

    # 9. Select first pane
    cmds.append(_exec("tmux", "select-pane", "-t", f"{session_name}:0.0"))

    # 10. Final: interactive attach (caller should execvp this one)
    cmds.append(
        ["docker", "exec", "-it", container_name, "tmux", "attach-session", "-t", session_name]
    )

    return cmds
