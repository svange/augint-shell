#!/bin/sh
# tmux-help: print a quick reference for tmux and ai-shell --tmux workspaces.
cat << 'EOF'
================================================================================
  TMUX & AI-SHELL WORKSPACE -- QUICK CHEAT SHEET (tmux-help | ai-shell tmux)
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
================================================================================
EOF
