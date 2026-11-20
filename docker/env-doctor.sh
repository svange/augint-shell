#!/bin/sh
# env-doctor: diagnose container Python (uv), Node.js (pnpm), PATH, CLI tools, and .env/mount health.
#
# Standalone container diagnostic script (does not collide with chezmoi's `dots-doctor`).
#
# Checks:
#   1. Python & uv environment (no pyenv/pipx conflicts, uv + uv-managed python)
#   2. Node.js & pnpm environment (no nvm conflicts, pnpm + pnpm-managed node)
#   3. PATH priority and installed editor/terminal/network/system CLI tools
#   4. Shell init, .env files, mounts, and chezmoi state
#
# Options:
#   -h, --help   show this help
set -u

for a in "$@"; do
  case "$a" in
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "[env-doctor] ERROR: unknown option: $a" >&2; exit 2 ;;
  esac
done

issues=0
ok()   { echo "  [OK]   $1"; }
info() { echo "  [INFO] $1"; }
warn() { issues=$((issues + 1)); echo "  [WARN] $1" >&2; [ -n "${2:-}" ] && echo "         -> Fix: $2" >&2; }

echo "[env-doctor] Running container environment diagnostics..."

echo ""
echo "==> 1. Python & uv Environment"
if [ -d "$HOME/.pyenv" ] || [ -n "${PYENV_ROOT:-}" ]; then
  warn "pyenv detected (~/.pyenv or PYENV_ROOT)." "Prefer 'uv python install 3.13 --default' and remove pyenv."
else
  ok "No pyenv conflicts detected."
fi

if command -v pipx >/dev/null 2>&1; then
  warn "pipx is installed ($(command -v pipx)) and shares ~/.local/bin with uv." "Prefer 'uv tool install <pkg>'."
else
  ok "No conflicting pipx installation found."
fi

if command -v uv >/dev/null 2>&1; then
  ok "uv is installed ($(command -v uv))."
else
  warn "uv is not installed." "Rebuild the augint-shell container image."
fi

if py_path=$(command -v python 2>/dev/null); then
  case "$py_path" in
    "$HOME/.local/bin/"*) ok "python resolves to uv-managed shim ($py_path)." ;;
    *) warn "python resolves to $py_path instead of $HOME/.local/bin/python." "Ensure $HOME/.local/bin precedes system directories on PATH." ;;
  esac
else
  warn "python is not on PATH." "Run 'uv python install 3.13 --default'."
fi

echo ""
echo "==> 2. Node.js & pnpm Environment"
export PNPM_HOME="${PNPM_HOME:-$HOME/.local/share/pnpm}"
if [ -d "$HOME/.nvm" ] || [ -n "${NVM_DIR:-}" ]; then
  warn "nvm detected (~/.nvm or NVM_DIR)." "pnpm manages Node LTS natively via 'pnpm runtime set node lts -g'."
else
  ok "No nvm conflicts detected."
fi

if command -v pnpm >/dev/null 2>&1; then
  ok "pnpm is installed ($(command -v pnpm))."
else
  warn "pnpm is not installed." "Rebuild the augint-shell container image."
fi

if node_path=$(command -v node 2>/dev/null); then
  case "$node_path" in
    "$PNPM_HOME"/*) ok "node resolves to pnpm-managed Node.js ($node_path)." ;;
    *) warn "node resolves to $node_path instead of $PNPM_HOME." "Ensure \$PNPM_HOME/bin and \$PNPM_HOME precede system directories on PATH." ;;
  esac
else
  warn "node is not on PATH." "Run 'pnpm runtime set node lts -g'."
fi

echo ""
echo "==> 3. PATH & CLI Tools"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ok "$HOME/.local/bin is on PATH." ;;
  *) warn "$HOME/.local/bin is not on PATH." "Add export PATH=\"\$HOME/.local/bin:\$PATH\" to ~/.bashrc." ;;
esac

case ":$PATH:" in
  *":$PNPM_HOME/bin:"*|*":$PNPM_HOME:"*) ok "$PNPM_HOME is on PATH." ;;
  *) warn "$PNPM_HOME is not on PATH." "Add \$PNPM_HOME/bin and \$PNPM_HOME to PATH." ;;
esac

missing_tools=""
for tool in vim nvim tmux starship zoxide fzf rg fd bat lsd delta lazygit yazi jq yq dig doggo nc tcpdump tshark ip ss nmap mtr trip gping xh htop btop btm procs dust duf fastfetch gitleaks tldr glow; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    missing_tools="$missing_tools $tool"
  fi
done
if [ -z "$missing_tools" ]; then
  ok "All core editor, terminal, network, and monitoring tools are installed."
else
  warn "Missing CLI tools:$missing_tools" "Rebuild the augint-shell container image."
fi

if [ -f "$HOME/.bashrc" ] && grep -q "# >>> dots-shell-init >>>" "$HOME/.bashrc" 2>/dev/null; then
  ok "~/.bashrc has the shell init block (Starship, zoxide, fzf, aliases)."
else
  warn "~/.bashrc is missing the shell init block." "Rebuild the augint-shell container image or check ~/.bashrc."
fi

echo ""
echo "==> 4. .env Configuration, Mounts & chezmoi"
if [ -f "$HOME/.augint/.env" ]; then
  ok "Global augint .env present ($HOME/.augint/.env)."
else
  info "Global augint .env not mounted ($HOME/.augint/.env)."
fi

if [ -f ".env" ]; then
  ok "Project .env present ($(pwd)/.env)."
else
  info "No project .env in $(pwd)."
fi

if [ -d "$HOME/.ssh" ]; then
  ok "~/.ssh directory exists."
else
  info "~/.ssh directory not present."
fi

if command -v chezmoi >/dev/null 2>&1; then
  ok "chezmoi is installed ($(command -v chezmoi))."
  if [ -f "$HOME/.config/chezmoi/key.txt" ]; then
    ok "chezmoi secrets UNLOCKED ($HOME/.config/chezmoi/key.txt)."
  else
    info "chezmoi secrets LOCKED or uninitialized (run 'chezmoi init --apply <repo>' to apply dotfiles/.env)."
  fi
else
  warn "chezmoi is not installed." "Rebuild the augint-shell container image."
fi

if [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
  ok "GUI display forwarding active (DISPLAY=${DISPLAY:-unset}, WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-unset})."
else
  info "GUI display forwarding not active (start with '--gui' or set container.gui: true)."
fi

if [ -e "/dev/dxg" ] || command -v nvidia-smi >/dev/null 2>&1; then
  ok "GPU device passthrough detected."
else
  info "No GPU device passthrough active (start with '--gpu' or set container.gpu: true)."
fi

echo ""
if [ "$issues" -eq 0 ]; then
  echo "[env-doctor] Everything looks healthy!"
  exit 0
else
  echo "[env-doctor] Found $issues issue(s)." >&2
  exit 1
fi
