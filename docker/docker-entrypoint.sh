#!/bin/bash
set -e

# Copy Windows gitconfig if it exists and create Linux-compatible version
if [ -f /root/.gitconfig.windows ]; then
    # Copy all settings except SSL backend
    grep -v "sslbackend" /root/.gitconfig.windows > /root/.gitconfig || true
fi

# Configure Git to use GitHub CLI for authentication if token is present
if [ -n "$GH_TOKEN" ]; then
    git config --global credential.https://github.com.helper "!gh auth git-credential"
    git config --global credential.https://gist.github.com.helper "!gh auth git-credential"
fi

# Force gnutls SSL backend globally only
git config --global http.sslBackend gnutls

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

# Note: No cd command - Docker Compose working_dir handles the directory
exec "$@"
