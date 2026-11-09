#!/bin/bash
# =========================================================================
# AUTO-UPDATE: AI tool updater for augint-shell containers
#
# Keeps CLI tools (claude, codex, opencode, etc.) fresh inside
# long-running dev containers.  Designed to be easily removable — delete
# this file and the corresponding blocks in Dockerfile and
# docker-entrypoint.sh (search for "AUTO-UPDATE").
#
# Usage:
#   update-tools.sh --all              Update every tool
#   update-tools.sh --tool <name>      Update one tool (fg), rest (bg)
#   update-tools.sh --check <name>     Exit 0 if fresh, 1 if stale
#   update-tools.sh --ttl <seconds>    Override default 6-hour TTL
# =========================================================================
set -uo pipefail

# The state and log directories can be moved for a test run
# (tests/unit/test_update_tools.py); the container uses the defaults.
STATE_DIR="${AI_SHELL_UPDATE_STATE_DIR:-/var/run/ai-shell}"
MARKER_DIR="$STATE_DIR/update-markers"
LOG_DIR="${AI_SHELL_UPDATE_LOG_DIR:-/var/log/ai-shell}"
LOCK_FILE="$STATE_DIR/update.lock"
DEFAULT_TTL=21600  # 6 hours in seconds
# How long the background pass after `--tool` waits before it starts, so the
# session that asked for the foreground update has connected its MCP servers
# by the time any `npm install -g` runs (see _npm_update).
BG_DELAY="${AI_SHELL_UPDATE_BG_DELAY:-90}"

ALL_TOOLS="claude codex opencode pi t3 npm-tools"

# ---- argument parsing ----------------------------------------------------
ACTION=""
TOOL_NAME=""
TTL="$DEFAULT_TTL"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --all)    ACTION="all";   shift ;;
        --tool)   ACTION="tool";  TOOL_NAME="$2"; shift 2 ;;
        --check)  ACTION="check"; TOOL_NAME="$2"; shift 2 ;;
        --ttl)    TTL="$2";       shift 2 ;;
        *)        echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

if [[ -z "$ACTION" ]]; then
    echo "Usage: update-tools.sh --all | --tool <name> | --check <name> [--ttl <seconds>]" >&2
    exit 2
fi

# ---- helpers -------------------------------------------------------------
mkdir -p "$MARKER_DIR" "$LOG_DIR"

_now() { date +%s; }

_is_fresh() {
    local tool="$1"
    local marker="$MARKER_DIR/${tool}.timestamp"
    [[ -f "$marker" ]] || return 1
    local last_update now age
    last_update=$(cat "$marker")
    now=$(_now)
    age=$((now - last_update))
    [[ "$age" -lt "$TTL" ]]
}

_mark_updated() {
    local tool="$1"
    _now > "$MARKER_DIR/${tool}.timestamp"
}

_log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# ---- npm helpers ---------------------------------------------------------
# `npm install -g <pkg>@latest` unlinks and relinks every bin of every named
# package under /usr/bin while it runs, whether or not the version changed.
# A Claude Code session that starts in that window finds its MCP server
# binary missing ("Executable not found in $PATH: chrome-devtools-mcp") and
# the server stays failed for the whole session. So the install runs only
# when at least one package is behind its published latest.

# Exit 0 when every named package is installed globally at its latest
# version; 1 when one is missing or behind, or when npm cannot say.
_npm_current() {
    local installed pkg latest have
    installed=$(npm ls -g --depth=0 --json 2>/dev/null) || return 1
    for pkg in "$@"; do
        latest=$(npm view "$pkg" version 2>/dev/null) || return 1
        have=$(printf '%s' "$installed" | jq -r --arg p "$pkg" '.dependencies[$p].version // empty' 2>/dev/null)
        [[ -n "$have" && "$have" == "$latest" ]] || return 1
    done
    return 0
}

# Install the named packages at @latest, unless every one is already there.
_npm_update() {
    if _npm_current "$@"; then
        _log "already at latest: $*"
        return 0
    fi
    local specs=()
    local pkg
    for pkg in "$@"; do specs+=("${pkg}@latest"); done
    npm install -g "${specs[@]}" 2>&1 || true
}

# ---- per-tool update functions -------------------------------------------
# Each function returns 0 on success.  Failures are logged but never fatal.

_update_claude() {
    _log "Updating claude..."
    if command -v claude >/dev/null 2>&1; then
        claude update --yes 2>&1 || true
    else
        curl -fsSL https://claude.ai/install.sh | bash 2>&1 || true
    fi
}

_update_codex() {
    _log "Updating codex..."
    _npm_update @openai/codex
}

_update_opencode() {
    _log "Updating opencode..."
    curl -fsSL https://opencode.ai/install | bash 2>&1 || true
}

_update_pi() {
    _log "Updating pi..."
    _npm_update @mariozechner/pi-coding-agent
}

_update_t3() {
    _log "Updating t3..."
    _npm_update t3
}

_update_npm_tools() {
    _log "Updating npm tools (aws-cdk, playwright-cli, agent-browser, zapier, chrome-devtools-mcp, ACP adapters)..."
    _npm_update aws-cdk @playwright/cli agent-browser zapier-platform-cli chrome-devtools-mcp \
        @agentclientprotocol/claude-agent-acp @agentclientprotocol/codex-acp
}

_update_tool() {
    local tool="$1"
    case "$tool" in
        claude)     _update_claude    ;;
        codex)      _update_codex     ;;
        opencode)   _update_opencode  ;;
        pi)         _update_pi        ;;
        t3)         _update_t3        ;;
        npm-tools)  _update_npm_tools ;;
        *)
            _log "Unknown tool: $tool"
            return 1
            ;;
    esac
    _mark_updated "$tool"
}

# ---- actions -------------------------------------------------------------

case "$ACTION" in
    check)
        # Exit 0 if fresh, 1 if stale
        if _is_fresh "$TOOL_NAME"; then
            exit 0
        else
            exit 1
        fi
        ;;

    tool)
        # Update the requested tool in foreground (blocking)
        (
            flock -w 300 9 || { _log "Could not acquire lock, skipping"; exit 0; }
            _log "Foreground update: $TOOL_NAME"
            _update_tool "$TOOL_NAME"
        ) 9>"$LOCK_FILE"

        # Update everything else in background, after a pause: the caller
        # is about to start a session, and an install that relinks /usr/bin
        # must not overlap its MCP server spawn.
        (
            sleep "$BG_DELAY"
            flock -n 9 || exit 0  # skip if another update is running
            for t in $ALL_TOOLS; do
                [[ "$t" == "$TOOL_NAME" ]] && continue
                _is_fresh "$t" && continue
                _update_tool "$t"
            done
        ) 9>"$LOCK_FILE" >> "$LOG_DIR/background-update.log" 2>&1 &
        ;;

    all)
        # Update every stale tool (used by cron and initial boot)
        (
            flock -n 9 || { _log "Another update is running, skipping"; exit 0; }
            for t in $ALL_TOOLS; do
                _is_fresh "$t" && { _log "$t is fresh, skipping"; continue; }
                _update_tool "$t"
            done
        ) 9>"$LOCK_FILE"
        ;;
esac
