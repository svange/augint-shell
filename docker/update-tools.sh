#!/bin/bash
# =========================================================================
# AUTO-UPDATE: AI tool updater for augint-shell containers
#
# Keeps CLI tools (claude, codex, aider, opencode, etc.) fresh inside
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

MARKER_DIR="/var/run/ai-shell/update-markers"
LOG_DIR="/var/log/ai-shell"
LOCK_FILE="/var/run/ai-shell/update.lock"
DEFAULT_TTL=21600  # 6 hours in seconds

ALL_TOOLS="claude codex aider opencode npm-tools"

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
    npm install -g @openai/codex@latest 2>&1 || true
}

_update_aider() {
    _log "Updating aider..."
    curl -LsSf https://aider.chat/install.sh | sh 2>&1 || true
}

_update_opencode() {
    _log "Updating opencode..."
    curl -fsSL https://opencode.ai/install | bash 2>&1 || true
}

_update_npm_tools() {
    _log "Updating npm tools (aws-cdk, playwright-cli, agent-browser)..."
    npm install -g aws-cdk@latest @playwright/cli@latest agent-browser@latest 2>&1 || true
}

_update_tool() {
    local tool="$1"
    case "$tool" in
        claude)     _update_claude    ;;
        codex)      _update_codex     ;;
        aider)      _update_aider     ;;
        opencode)   _update_opencode  ;;
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

        # Update everything else in background
        (
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
