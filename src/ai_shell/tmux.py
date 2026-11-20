"""tmux split-pane workspace builder (Neovim on the left, AI agent on the right)."""

from __future__ import annotations

import re
import shlex

TMUX_CHEATSHEET = """\
================================================================================
  TMUX & AI-SHELL WORKSPACE -- QUICK CHEAT SHEET (ai-shell tmux | tmux-help)
================================================================================
  Prefix key: Ctrl+B (release both, then press the command key)
  Mouse is ON: click to focus panes, drag borders to resize, scroll to browse.

1. AI-SHELL --tmux WORKSPACE (Neovim on left, AI agent on right)
  ai-shell claude --tmux       Launch Neovim (left) + Claude Code (right)
  ai-shell opencode --tmux     Launch Neovim (left) + OpenCode (right)
  ai-shell codex --tmux        Launch Neovim (left) + Codex (right)
  ai-shell pi --tmux           Launch Neovim (left) + Pi (right)
  ai-shell shell --tmux        Launch Neovim (left) + interactive shell (right)
  (Re-running --tmux re-attaches to the live session if you detached!)

2. PANES (splits inside the current window)
  Ctrl+B h / j / k / l         Move focus Left / Down / Up / Right (or click)
  Ctrl+B |                     Split pane side-by-side (vertical divider)
  Ctrl+B -                     Split pane top/bottom (horizontal divider)
  Ctrl+B z                     Toggle zoom on current pane (maximize / restore)
  Ctrl+B H / J / K / L         Resize current pane (or drag border with mouse)
  Ctrl+B { / }                 Swap current pane left / right
  Ctrl+B x                     Close current pane (prompts y/n)

3. WINDOWS (tabs) & SESSIONS
  Ctrl+B c                     New window (tab) in current directory
  Ctrl+B n / p / 1..9          Next / Previous / Jump to window number
  Ctrl+B ,                     Rename current window
  Ctrl+B d                     Detach (leaves Neovim + agent running in bg)
  Ctrl+B s                     Interactive session switcher
  tmux ls                      List running tmux sessions
  tmux attach -t <name>        Re-attach to a detached session

4. COPY MODE (scrollback & search) & CONFIG
  Ctrl+B [                     Enter scroll/copy mode (arrows, PgUp, / to search)
  v / y / q                    Begin selection / Yank selection / Exit copy mode
  Ctrl+B ]                     Paste yanked text
  Ctrl+B r                     Reload ~/.tmux.conf
  Ctrl+B ?                     Show all tmux keybindings
================================================================================"""


def sanitize_session_name(name: str) -> str:
    """Return a tmux-safe session name (no dots or colons)."""
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-")
    return cleaned or "ai-shell"


def build_tmux_workspace_cmd(
    agent_cmd: list[str],
    *,
    session_name: str,
    agent_label: str = "agent",
    editor_cmd: str = "nvim",
) -> list[str]:
    """Build a container command that opens a split tmux workspace.

    Layout:
      - Left pane:  Neovim (drops to a login bash shell if ``:q`` is run)
      - Right pane: *agent_cmd* (focused on launch)

    If a tmux session named *session_name* already exists in the container,
    the command re-attaches to it instead of creating a duplicate session.
    """
    session = sanitize_session_name(session_name)
    s_q = shlex.quote(session)
    label_q = shlex.quote(agent_label)
    left_shell = shlex.quote(f"{editor_cmd}; exec bash -l")
    agent_str = shlex.join(agent_cmd)
    right_shell = shlex.quote(f"exec {agent_str}")
    status_hint = shlex.quote(" ^B h/l pane | ^B z zoom | ^B d detach | tmux-help ")

    script = (
        f"if ! command -v tmux >/dev/null 2>&1; then "
        f"echo '[warn] tmux is not installed in this container; running directly.' >&2; "
        f"exec {agent_str}; "
        f"fi; "
        f"if tmux has-session -t {s_q} 2>/dev/null; then "
        f"exec tmux attach-session -t {s_q}; "
        f"fi; "
        f'LEFT_PANE=$(tmux new-session -d -P -F "#{{pane_id}}" -s {s_q} -c "$PWD" '
        f"bash -lc {left_shell}); "
        f'tmux select-pane -t "$LEFT_PANE" -T {shlex.quote(editor_cmd)}; '
        f'RIGHT_PANE=$(tmux split-window -h -P -F "#{{pane_id}}" -t "$LEFT_PANE" -c "$PWD" '
        f"bash -lc {right_shell}); "
        f'tmux select-pane -t "$RIGHT_PANE" -T {label_q}; '
        f"tmux set-option -t {s_q} pane-border-status top; "
        f"tmux set-option -t {s_q} mouse on; "
        f"tmux set-option -t {s_q} status-right {status_hint}; "
        f'tmux select-pane -t "$RIGHT_PANE"; '
        f"exec tmux attach-session -t {s_q}"
    )
    return ["bash", "-lc", script]
