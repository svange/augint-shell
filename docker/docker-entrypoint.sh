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

# Configure Git to use GitHub CLI for authentication if token is present
if [ -n "$GH_TOKEN" ]; then
    git config --global credential.https://github.com.helper "!gh auth git-credential"
    git config --global credential.https://gist.github.com.helper "!gh auth git-credential"
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

if [ -f "package-lock.json" ]; then
    echo "===================================="
    echo "Installing Node.js dependencies..."
    echo "===================================="
    npm ci --loglevel=warn
    echo "===================================="
    echo "Node.js dependencies installed!"
    echo "===================================="
elif [ -f "package.json" ]; then
    echo "===================================="
    echo "Installing Node.js dependencies..."
    echo "===================================="
    npm install --loglevel=warn
    echo "===================================="
    echo "Node.js dependencies installed!"
    echo "===================================="
fi

# =========================================================================
# AUTO-UPDATE: Background cron + initial tool update
# Remove this block to disable auto-updates.
# =========================================================================
if [ -x /usr/local/bin/update-tools.sh ] && command -v cron >/dev/null 2>&1; then
    echo "0 */6 * * * flock -n /var/run/ai-shell/update.lock /usr/local/bin/update-tools.sh --all >> /var/log/ai-shell/cron-update.log 2>&1" | crontab -
    cron
    /usr/local/bin/update-tools.sh --all >> /var/log/ai-shell/initial-update.log 2>&1 &
fi
# =========================================================================

# Display MOTD (environment status dashboard)
if [ -x /usr/local/bin/motd.sh ]; then
    /usr/local/bin/motd.sh || true
fi

# Note: No cd command - Docker Compose working_dir handles the directory
exec "$@"
