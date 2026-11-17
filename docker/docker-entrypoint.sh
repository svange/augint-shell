#!/bin/bash
set -e

# Copy Windows gitconfig if it exists and create Linux-compatible version
if [ -f /root/.gitconfig.windows ]; then
    # Copy all settings except SSL backend
    grep -v "sslbackend" /root/.gitconfig.windows > /root/.gitconfig || true
fi

# Re-apply container-critical git settings that the Windows gitconfig copy
# above may have overwritten (mirrors Dockerfile lines 206-214).
git config --global --add safe.directory '*'
git config --global core.filemode false
# Clear any core.hooksPath inherited from Windows gitconfig so pre-commit
# hooks can fire normally inside the container.
git config --global --unset-all core.hooksPath 2>/dev/null || true
git config --global init.defaultBranch main
git config --global color.ui auto
git config --global core.editor vim

# Prefer SSO keyring token over the env-var PAT.
# When ~/.config/gh is mounted, the SSO token carries org-level access that a PAT
# scoped to a personal account may lack (e.g. private marketplace plugins in augmenting-integrations).
#
# SCOPE: this runs only in PID 1 (the entrypoint), so it governs the entrypoint
# itself and its background children (uv sync, the auto-update cron, pi installs).
# Interactive tools (`ai-shell claude|codex|opencode|pi|shell`) launch via
# `docker exec`, which does NOT re-run this entrypoint and does NOT inherit these
# exports; those sessions receive their env from build_dev_environment (and any
# GH_TOKEN injected via `--env` / ~/.augint/.env, which the exec passes with -e).
# So for interactive tools a PAT supplied via env overrides the mounted SSO token.
_SAVED_GH_TOKEN="${GH_TOKEN:-}"
unset GH_TOKEN GITHUB_TOKEN
_SSO_TOKEN=$(gh auth token --hostname github.com 2>/dev/null || true)
if [ -n "$_SSO_TOKEN" ]; then
    export GH_TOKEN="$_SSO_TOKEN"
    export GITHUB_TOKEN="$_SSO_TOKEN"
else
    # No keyring token — fall back to the PAT passed via env
    [ -n "$_SAVED_GH_TOKEN" ] && export GH_TOKEN="$_SAVED_GH_TOKEN"
    [ -n "$_SAVED_GH_TOKEN" ] && export GITHUB_TOKEN="$_SAVED_GH_TOKEN"
fi
unset _SAVED_GH_TOKEN _SSO_TOKEN

# Drop any GitHub credential helpers inherited from the host gitconfig before
# configuring our own. `gh auth setup-git` writes two values (an empty reset
# plus the helper) and the helper path is a Windows gh.exe that cannot run
# here, so a plain `git config <key> <value>` set fails with "cannot overwrite
# multiple values with a single value" and takes the entrypoint down with it.
git config --global --unset-all "credential.https://github.com.helper" 2>/dev/null || true
git config --global --unset-all "credential.https://gist.github.com.helper" 2>/dev/null || true

# Configure Git to use GitHub CLI for authentication if token is present
if [ -n "$GH_TOKEN" ]; then
    git config --global "credential.https://github.com.helper" "!gh auth git-credential"
    git config --global "credential.https://gist.github.com.helper" "!gh auth git-credential"
fi

# Force gnutls SSL backend globally only
git config --global http.sslBackend gnutls

# Prune stale worktree references left by container-local worktrees that
# vanished on container recreation (no-op if no stale refs or not a git repo)
git worktree prune 2>/dev/null || true

# Install/sync project dependencies FIRST, before anything else starts
# This ensures Claude Code has access to all tools
if [ -f "uv.lock" ]; then
    echo "===================================="
    echo "Syncing project dependencies with uv..."
    echo "===================================="
    uv sync
    echo "===================================="
    echo "Dependencies synced successfully!"
    echo "===================================="
    # Note: uv automatically manages virtualenvs, no manual activation needed
    # Commands should be run with "uv run" prefix or use the activated venv
fi

# Install pre-commit hooks into the local .git/hooks directory.
# Container-local: PRE_COMMIT_HOME points to a named volume so this does not
# touch the Windows host's ~/.cache/pre-commit. Best-effort; never fail the
# entrypoint because of pre-commit issues (set -e is active).
if [ -f ".pre-commit-config.yaml" ] && [ -d ".git" ]; then
    echo "===================================="
    echo "Installing pre-commit hooks..."
    echo "===================================="
    uv run pre-commit install || true
    echo "===================================="
    echo "Pre-commit hooks installed!"
    echo "===================================="
fi

if [ -f "package.json" ]; then
    if [ -f "pnpm-lock.yaml" ]; then
        _pm="pnpm"
        _cmd="pnpm install --loglevel=warn"
    elif [ -f "yarn.lock" ]; then
        _pm="yarn"
        _cmd="yarn install --silent"
    elif [ -f "package-lock.json" ]; then
        _pm="npm"
        _cmd="npm ci --loglevel=warn"
    else
        _pm="npm"
        _cmd="npm install --loglevel=warn"
    fi
    echo "===================================="
    echo "Installing Node.js dependencies (${_pm})..."
    echo "===================================="
    if $_cmd; then
        echo "===================================="
        echo "Node.js dependencies installed!"
        echo "===================================="
    else
        echo "[warn] '${_cmd}' failed. Container will continue."
        echo "[warn] For npm: lockfile may be out of sync; run 'npm install' to regenerate."
    fi
    unset _pm _cmd
fi

if [ -f "composer.json" ] && command -v composer >/dev/null 2>&1; then
    echo "===================================="
    echo "Installing PHP dependencies (composer)..."
    echo "===================================="
    # First run also populates the per-project vendor/ overlay volume.
    if composer install --no-interaction; then
        echo "===================================="
        echo "PHP dependencies installed!"
        echo "===================================="
    else
        echo "[warn] 'composer install' failed. Container will continue."
    fi
fi

# =========================================================================
# AUTO-UPDATE: Background cron + initial tool update
# Remove this block to disable auto-updates.
# =========================================================================
if [ -x /usr/local/bin/update-tools.sh ] && command -v cron >/dev/null 2>&1; then
    echo "0 */6 * * * flock -n /var/run/ai-shell/update.lock /usr/local/bin/update-tools.sh --all >> /var/log/ai-shell/cron-update.log 2>&1" | crontab -
    cron
    # After a pause: the first session starts seconds after the container,
    # and an `npm install -g` relinks /usr/bin while it runs (update-tools.sh,
    # _npm_update), which a starting session's MCP server spawn must not hit.
    (sleep "${AI_SHELL_UPDATE_BOOT_DELAY:-120}" && /usr/local/bin/update-tools.sh --all) >> /var/log/ai-shell/initial-update.log 2>&1 &
fi
# =========================================================================

# =========================================================================
# Pi package bootstrap: install extensions listed in .pi/settings.json
# =========================================================================
if [ -f ".pi/settings.json" ] && command -v pi >/dev/null 2>&1; then
    _PI_PACKAGES=$(jq -r '.packages[]? // empty' .pi/settings.json 2>/dev/null)
    if [ -n "$_PI_PACKAGES" ]; then
        echo "===================================="
        echo "Installing Pi packages..."
        echo "===================================="
        echo "$_PI_PACKAGES" | while read -r _pkg; do
            [ -z "$_pkg" ] && continue
            echo "  -> $_pkg"
            pi install "$_pkg" 2>/dev/null || echo "  [warn] failed to install $_pkg"
        done
        echo "===================================="
        echo "Pi packages installed!"
        echo "===================================="
    fi
    unset _PI_PACKAGES
fi
# =========================================================================
# OpenCode state/config directories
# =========================================================================
mkdir -p /root/.config/opencode /root/.local/share/opencode
# Older images linked OpenCode's skills directory to the Claude Code or
# .agents skills. OpenCode always reads that directory, so the link loaded
# those skills even with OPENCODE_DISABLE_CLAUDE_CODE. Remove only that link.
case "$(readlink /root/.config/opencode/skills 2>/dev/null)" in
    /root/.agents/skills | /root/.claude/skills) rm -f /root/.config/opencode/skills ;;
esac
# =========================================================================

# Display MOTD only when not booting the background tail daemon (where output
# goes to container logs and is never seen by interactive docker exec sessions).
if [ "${1:-}" != "tail" ] && [ -x /usr/local/bin/motd.sh ]; then
    /usr/local/bin/motd.sh || true
fi

# Note: No cd command - Docker Compose working_dir handles the directory
exec "$@"
