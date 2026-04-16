"""Constants and configuration builders for augint-shell.

Encodes all docker-compose.yml configuration as Python, so no compose file is needed.
"""

from __future__ import annotations

import logging
import os
import re
from hashlib import sha1
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
GH_CONFIG_VOLUME = "augint-shell-gh-config"


def uv_venv_path(repo_name: str, worktree_name: str | None = None) -> str:
    """Return the ``UV_PROJECT_ENVIRONMENT`` path for a repo.

    Matches the venv isolation scheme used by both ``--multi`` and ``--team``
    modes.  When *worktree_name* is set, appends ``-wt-{worktree_name}`` to
    isolate worktree venvs.
    """
    suffix = repo_name
    if worktree_name:
        suffix = f"{repo_name}-wt-{worktree_name}"
    return f"/root/.cache/uv/venvs/{suffix}"


NPM_CACHE_VOLUME = "augint-shell-npm-cache"
OLLAMA_DATA_VOLUME = "augint-shell-ollama-data"
WEBUI_DATA_VOLUME = "augint-shell-webui-data"

# =============================================================================
# LLM defaults
# =============================================================================
OLLAMA_IMAGE = "ollama/ollama"
WEBUI_IMAGE = "ghcr.io/open-webui/open-webui:main"
DEFAULT_PRIMARY_MODEL = "qwen3-coder:32b-a3b-q4_K_M"
DEFAULT_FALLBACK_MODEL = "qwen3.5:27b"
DEFAULT_CONTEXT_SIZE = 32768
DEFAULT_OLLAMA_PORT = 11434
DEFAULT_WEBUI_PORT = 3000
DEFAULT_DEV_PORTS = [3000, 4200, 5000, 5173, 5678, 8000, 8080, 8888]

# =============================================================================
# Bedrock defaults
# =============================================================================
DEFAULT_BEDROCK_MODEL = "us.anthropic.claude-sonnet-4-20250514-v1:0"

# =============================================================================
# Ollama GPU defaults
# =============================================================================
OLLAMA_VRAM_BUFFER_BYTES = 1 * 1024**3  # 1 GiB safety buffer reserved as overhead
OLLAMA_CPU_SHARES = 1024  # Docker CPU scheduling priority (default 0 = fair-share)

# =============================================================================
# Container names
# =============================================================================
OLLAMA_CONTAINER = "augint-shell-ollama"
WEBUI_CONTAINER = "augint-shell-webui"

# =============================================================================
# Docker network
# =============================================================================
LLM_NETWORK = "augint-shell-llm"


def _sanitize_name(name: str) -> str:
    """Convert an arbitrary string into a Docker-safe slug."""
    name = re.sub(r"[^a-z0-9-]", "-", name)
    name = re.sub(r"-+", "-", name)
    return name.strip("-") or "project"


def sanitize_project_name(path: Path) -> str:
    """Derive a safe project slug from a directory basename."""
    return _sanitize_name(path.resolve().name.lower())


def unique_project_name(path: Path, project_name: str | None = None) -> str:
    """Build a path-stable project identifier for container naming.

    The basename remains human-readable while a short path hash prevents
    collisions between repos with the same leaf directory name.
    """
    slug = _sanitize_name((project_name or path.resolve().name).lower())
    digest = sha1(str(path.resolve()).encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    return f"{slug}-{digest}"


def dev_container_name(project_name: str, project_dir: Path | None = None) -> str:
    """Build the dev container name for a project.

    When *project_dir* is provided, the full resolved path is folded into the
    name to avoid collisions across nested repo layouts. Without it, the legacy
    basename-only format is preserved for compatibility.
    """
    if project_dir is None:
        return f"{CONTAINER_PREFIX}-{project_name}-dev"
    return f"{CONTAINER_PREFIX}-{unique_project_name(project_dir, project_name)}-dev"


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

    # gh CLI config: bind-mount the host path when found (Linux/Mac/WSL2),
    # otherwise use a named volume so auth persists across container recreations
    # (needed on Windows where gh stores tokens in keyring, not a file).
    gh_config = _find_gh_config_dir()
    if gh_config is not None:
        mounts.append(
            Mount(
                target="/root/.config/gh",
                source=str(gh_config),
                type="bind",
                read_only=False,
            )
        )
    else:
        mounts.append(
            Mount(
                target="/root/.config/gh",
                source=GH_CONFIG_VOLUME,
                type="volume",
            )
        )

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

    # Named volume: npm cache (shared across all projects)
    mounts.append(
        Mount(
            target="/root/.npm",
            source=NPM_CACHE_VOLUME,
            type="volume",
        )
    )

    return mounts


def _find_gh_config_dir() -> Path | None:
    """Find the gh CLI config directory.

    Checks the standard Linux/Mac path (~/.config/gh) first, then falls back
    to the Windows APPDATA path for WSL2 environments where gh is installed on
    the Windows side (%APPDATA%\\GitHub CLI\\).
    """
    linux_path = Path.home() / ".config" / "gh"
    if linux_path.exists():
        return linux_path

    # WSL2 fallback: APPDATA is set as a Windows path (e.g. C:\Users\foo\AppData\Roaming)
    appdata = os.environ.get("APPDATA", "")
    if appdata and ":" in appdata:
        drive, rest = appdata.split(":", 1)
        wsl_appdata = Path(f"/mnt/{drive.lower()}{rest.replace(chr(92), '/')}")
        windows_path = wsl_appdata / "GitHub CLI"
        if windows_path.exists():
            return windows_path

    return None


def build_dev_environment(
    extra_env: dict[str, str] | None = None,
    project_dir: Path | None = None,
    *,
    project_name: str = "",
    bedrock: bool = False,
    aws_profile: str = "",
    aws_region: str = "",
    bedrock_profile: str = "",
    team_mode: bool = False,
) -> dict[str, str]:
    """Build environment variables matching docker-compose.yml dev service.

    Loads .env from the project directory (if present), then layers on
    host environment variables and hardcoded defaults.

    Priority (highest wins): extra_env > .env file > os.environ > defaults.

    When *bedrock* is True, ``CLAUDE_CODE_USE_BEDROCK=1`` is injected and
    *bedrock_profile* (if set) overrides ``AWS_PROFILE`` so the LLM provider
    authenticates with the correct AWS account.

    When *team_mode* is True, ``CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`` is
    injected to enable Claude Code's Agent Teams feature.
    """
    from dotenv import dotenv_values

    # Load .env from project directory (returns empty dict if missing)
    dotenv: dict[str, str | None] = {}
    if project_dir is not None:
        dotenv = dotenv_values(project_dir / ".env")

    def _resolve(key: str, default: str = "") -> str:
        """Resolve a value: .env > os.environ > default."""
        dotenv_val = dotenv.get(key)
        if dotenv_val is not None and dotenv_val != "":
            return dotenv_val
        return os.environ.get(key, default)

    gh_token = _resolve("GH_TOKEN")
    env: dict[str, str] = {
        "AWS_PROFILE": aws_profile or _resolve("AWS_PROFILE"),
        "AWS_REGION": aws_region or _resolve("AWS_REGION", "us-east-1"),
        "AWS_PAGER": "",
        "GH_TOKEN": gh_token,
        "GITHUB_TOKEN": gh_token,
        "HUSKY": "0",
        "IS_SANDBOX": "1",
    }

    # Mirror AWS_REGION to AWS_DEFAULT_REGION so both Node.js SDK paths resolve
    env["AWS_DEFAULT_REGION"] = env["AWS_REGION"]

    # Isolate UV venvs per-project within the shared cache volume.
    # Overrides Dockerfile default of /root/.cache/uv/venvs/project.
    if project_name:
        env["UV_PROJECT_ENVIRONMENT"] = uv_venv_path(project_name)

    if bedrock:
        env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        if bedrock_profile:
            env["AWS_PROFILE"] = bedrock_profile

    if team_mode:
        env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"

    if extra_env:
        env.update(extra_env)

    return env
