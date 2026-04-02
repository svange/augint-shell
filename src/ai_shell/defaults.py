"""Constants and configuration builders for augint-shell.

Encodes all docker-compose.yml configuration as Python, so no compose file is needed.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docker.types import Mount

logger = logging.getLogger(__name__)

# =============================================================================
# Image defaults
# =============================================================================
DEFAULT_IMAGE = "svange/augint-shell"
CONTAINER_PREFIX = "augint-shell"
SHM_SIZE = "2g"

# =============================================================================
# Volume names (prefixed to avoid collisions)
# =============================================================================
UV_CACHE_VOLUME = "augint-shell-uv-cache"
OLLAMA_DATA_VOLUME = "augint-shell-ollama-data"
WEBUI_DATA_VOLUME = "augint-shell-webui-data"

# =============================================================================
# LLM defaults
# =============================================================================
OLLAMA_IMAGE = "ollama/ollama"
WEBUI_IMAGE = "ghcr.io/open-webui/open-webui:main"
DEFAULT_PRIMARY_MODEL = "qwen3.5:27b"
DEFAULT_FALLBACK_MODEL = "qwen3-coder-next"
DEFAULT_CONTEXT_SIZE = 32768
DEFAULT_OLLAMA_PORT = 11434
DEFAULT_WEBUI_PORT = 3000

# =============================================================================
# Container names
# =============================================================================
OLLAMA_CONTAINER = "augint-shell-ollama"
WEBUI_CONTAINER = "augint-shell-webui"

# =============================================================================
# Docker network
# =============================================================================
LLM_NETWORK = "augint-shell-llm"


def sanitize_project_name(path: Path) -> str:
    """Derive a safe container name suffix from a directory path.

    Converts the directory basename to lowercase, replaces non-alphanumeric
    characters with hyphens, and strips leading/trailing hyphens.
    """
    name = path.resolve().name.lower()
    name = re.sub(r"[^a-z0-9-]", "-", name)
    name = re.sub(r"-+", "-", name)
    return name.strip("-") or "project"


def dev_container_name(project_name: str) -> str:
    """Build the dev container name for a project."""
    return f"{CONTAINER_PREFIX}-{project_name}-dev"


def build_dev_mounts(project_dir: Path, project_name: str) -> list[Mount]:
    """Build the full mount list matching docker-compose.yml dev service.

    Required mounts are always included. Optional mounts are skipped
    if the source path doesn't exist on the host.
    """
    from docker.types import Mount

    mounts: list[Mount] = []
    home = Path.home()

    # Required: project directory (rw, delegated)
    mounts.append(
        Mount(
            target=f"/root/projects/{project_name}",
            source=str(project_dir.resolve()),
            type="bind",
            read_only=False,
            consistency="delegated",
        )
    )

    # Optional bind mounts — skip if source doesn't exist
    optional_binds: list[tuple[Path, str, bool]] = [
        (home / ".codex", "/root/.codex", False),
        (home / ".claude", "/root/.claude", False),
        (home / ".claude.json", "/root/.claude.json", False),
        (home / "projects" / "CLAUDE.md", "/root/projects/CLAUDE.md", True),
        (home / ".ssh", "/root/.ssh", True),
        (home / ".gitconfig", "/root/.gitconfig.windows", True),
        (home / ".aws", "/root/.aws", False),
    ]

    for source, target, read_only in optional_binds:
        if source.exists():
            mounts.append(
                Mount(
                    target=target,
                    source=str(source),
                    type="bind",
                    read_only=read_only,
                )
            )
        else:
            logger.debug("Skipping optional mount (not found): %s", source)

    # Optional: Docker socket
    docker_sock = Path("/var/run/docker.sock")
    if docker_sock.exists():
        mounts.append(
            Mount(
                target="/var/run/docker.sock",
                source=str(docker_sock),
                type="bind",
                read_only=True,
            )
        )

    # Named volume: uv cache (shared across all projects)
    mounts.append(
        Mount(
            target="/root/.cache/uv",
            source=UV_CACHE_VOLUME,
            type="volume",
        )
    )

    return mounts


def build_dev_environment(extra_env: dict[str, str] | None = None) -> dict[str, str]:
    """Build environment variables matching docker-compose.yml dev service.

    Passes through AWS credentials, GitHub token, and sandbox flag from the host.
    """
    env: dict[str, str] = {
        # AWS region (auth via SSO/OIDC, not static credentials)
        "AWS_REGION": os.environ.get("AWS_REGION", "us-east-1"),
        "AWS_PAGER": "",
        # GitHub token
        "GH_TOKEN": os.environ.get("GH_TOKEN", ""),
        "GITHUB_TOKEN": os.environ.get("GH_TOKEN", ""),
        # Sandbox mode for claude --dangerously-skip-permissions
        "IS_SANDBOX": "1",
    }

    if extra_env:
        env.update(extra_env)

    return env
