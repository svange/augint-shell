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
    from collections.abc import Callable

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
NODE_MODULES_VOLUME_PREFIX = "augint-shell-node-modules-"


def node_modules_volume_name(
    repo_name: str,
    worktree_name: str | None = None,
    subpath: str | None = None,
) -> str:
    """Per-project named volume that overlays a node_modules directory.

    Mirrors the UV venv-isolation scheme so the container's Linux node_modules
    never collides with the host's (e.g. Windows-built) node_modules in the
    bind-mounted project directory.

    When *subpath* is given (e.g. ``"apps/web"``), a sanitized slug is appended
    so monorepos can isolate each workspace's node_modules independently.
    """
    suffix = repo_name
    if worktree_name:
        suffix = f"{repo_name}-wt-{worktree_name}"
    if subpath:
        suffix = f"{suffix}-{_sanitize_name(subpath.lower())}"
    return f"{NODE_MODULES_VOLUME_PREFIX}{suffix}"


COMPOSER_CACHE_VOLUME = "augint-shell-composer-cache"
PNPM_STORE_VOLUME = "augint-shell-pnpm-store"
VENDOR_VOLUME_PREFIX = "augint-shell-vendor-"


def vendor_volume_name(repo_name: str, worktree_name: str | None = None) -> str:
    """Per-project named volume that overlays composer's ``vendor/`` directory.

    Same rationale as :func:`node_modules_volume_name`: ``vendor/`` on a
    drvfs/9p bind mount is slow, and overlaying keeps the container's
    Linux-built vendor tree separate from whatever the host has.
    """
    suffix = repo_name
    if worktree_name:
        suffix = f"{repo_name}-wt-{worktree_name}"
    return f"{VENDOR_VOLUME_PREFIX}{suffix}"


PRE_COMMIT_CACHE_VOLUME = "augint-shell-pre-commit-cache"
PRE_COMMIT_CACHE_PATH = "/root/.cache/pre-commit-container"
OLLAMA_DATA_VOLUME = "augint-shell-ollama-data"
WEBUI_DATA_VOLUME = "augint-shell-webui-data"
N8N_DATA_VOLUME = "augint-shell-n8n-data"
WHISPER_DATA_VOLUME = "augint-shell-whisper-cache"
VOICE_AGENT_DATA_VOLUME = "augint-shell-voice-agent-data"
COMFYUI_DATA_VOLUME = "augint-shell-comfyui-data"

# =============================================================================
# LLM defaults
# =============================================================================
OLLAMA_IMAGE = "ollama/ollama"
WEBUI_IMAGE = "ghcr.io/open-webui/open-webui:main"
KOKORO_IMAGE_CPU = "ghcr.io/remsky/kokoro-fastapi-cpu:latest"
KOKORO_IMAGE_GPU = "ghcr.io/remsky/kokoro-fastapi-gpu:latest"
N8N_IMAGE = "docker.n8n.io/n8nio/n8n"
WHISPER_IMAGE_CPU = "ghcr.io/speaches-ai/speaches:latest-cpu"
WHISPER_IMAGE_GPU = "ghcr.io/speaches-ai/speaches:latest-cuda"
# Voice-agent image is built locally from docker/voice-agent/ on first
# ensure call. Not pulled. The local tag keeps `images.get` fast once built.
VOICE_AGENT_IMAGE = "augint-shell/voice-agent:local"
# ComfyUI: ai-dock/comfyui is actively maintained and exposes PROVISIONING_SCRIPT
# which we use to download FLUX.1-dev + SDXL on first boot. GPU-only (no CPU variant).
COMFYUI_IMAGE = "ghcr.io/ai-dock/comfyui:latest-cuda"
# Model slots (RTX 4090-sized, validated April 2026). Primary = best available for
# the role; secondary = best uncensored alternative. See README "Local LLM stack"
# and the generated .ai-shell.yaml for per-slot rationale and caveats.
DEFAULT_PRIMARY_CHAT_MODEL = "qwen3.5:27b"
DEFAULT_SECONDARY_CHAT_MODEL = "huihui_ai/qwen3.5-abliterated:27b"
DEFAULT_PRIMARY_CODING_MODEL = "qwen3-coder:30b-a3b-q4_K_M"
DEFAULT_SECONDARY_CODING_MODEL = "huihui_ai/qwen3-coder-abliterated:30b-a3b-instruct-q4_K_M"
DEFAULT_EXTRA_MODELS: list[str] = [
    "qwen3.5:9b",  # ~6.6 GB  mid-range chat, fast + capable
    "devstral:24b",  # ~15 GB  Mistral agentic coding, dense 24B
]
DEFAULT_CONTEXT_SIZE = 32768
DEFAULT_OLLAMA_PORT = 11434
DEFAULT_WEBUI_PORT = 3000
DEFAULT_KOKORO_PORT = 8880
DEFAULT_N8N_PORT = 5678
DEFAULT_WHISPER_PORT = 8001
DEFAULT_WHISPER_MODEL = "Systran/faster-distil-whisper-large-v3"
DEFAULT_VOICE_AGENT_PORT = 8010
DEFAULT_COMFYUI_PORT = 8188
DEFAULT_KOKORO_VOICE = "af_bella"
DEFAULT_DEV_PORTS = [3000, 4096, 4200, 5000, 5173, 5678, 8000, 8080, 8888, 19432, 31415]

# Deterministic dev port mapping (avoids Chrome debug range 40000-60000)
DEV_PORT_RANGE_START = 10000
DEV_PORT_RANGE_SIZE = 30000  # 10000-39999

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
KOKORO_CONTAINER = "augint-shell-kokoro"
N8N_CONTAINER = "augint-shell-n8n"
WHISPER_CONTAINER = "augint-shell-whisper"
VOICE_AGENT_CONTAINER = "augint-shell-voice-agent"
COMFYUI_CONTAINER = "augint-shell-comfyui"

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
    # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
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


# Salted re-hash attempts per port before giving up. Each attempt is an
# independent draw from 30000 slots, so exhaustion means the host is
# rejecting essentially the whole range.
DEV_PORT_MAX_ATTEMPTS = 64


def project_dev_port_map(
    project_dir: Path,
    dev_ports: list[int],
    project_name: str | None = None,
    is_available: Callable[[int], bool] | None = None,
) -> dict[int, int]:
    """Map each container port to a unique, stable per-project host port.

    Uses the same project identity as container naming (unique_project_name)
    combined with each container port to produce deterministic host ports in
    the 10000-39999 range. Different projects get different host ports for
    the same container port, so multiple projects can run simultaneously.

    A candidate slot is rejected when it is already taken by another port in
    this map or when *is_available* (e.g. a host test-bind probe) refuses it.
    Rejected candidates are re-hashed with a salt counter rather than probed
    linearly: host-side reservations (Windows winnat excluded port ranges)
    are contiguous blocks, so adjacent slots tend to fail together while a
    re-hash jumps elsewhere in the range. Assignment runs in ascending
    container-port order so the result is deterministic, and an unsalted
    first attempt keeps existing assignments stable for the common case.
    """
    slug = unique_project_name(project_dir, project_name)
    assigned: dict[int, int] = {}
    used: set[int] = set()
    for port in sorted(set(dev_ports)):
        for salt in range(DEV_PORT_MAX_ATTEMPTS):
            key = f"{slug}:{port}" if salt == 0 else f"{slug}:{port}:{salt}"
            # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
            digest = sha1(key.encode(), usedforsecurity=False).hexdigest()
            candidate = DEV_PORT_RANGE_START + (int(digest[:8], 16) % DEV_PORT_RANGE_SIZE)
            if candidate not in used and (is_available is None or is_available(candidate)):
                break
        else:
            raise RuntimeError(
                f"Could not find a free host port for container port {port} "
                f"after {DEV_PORT_MAX_ATTEMPTS} attempts in range "
                f"{DEV_PORT_RANGE_START}-{DEV_PORT_RANGE_START + DEV_PORT_RANGE_SIZE - 1}. "
                "The host is rejecting nearly all bind attempts — check firewall "
                "or reserved port configuration."
            )
        assigned[port] = candidate
        used.add(candidate)
    return assigned


def project_dev_port(
    project_dir: Path,
    container_port: int,
    project_name: str | None = None,
    dev_ports: list[int] | None = None,
) -> int:
    """Host port for one container port, consistent with project_dev_port_map.

    *dev_ports* must be the full port set the container was created with —
    collision resolution depends on it. Defaults to DEFAULT_DEV_PORTS.
    """
    ports = list(dev_ports) if dev_ports is not None else list(DEFAULT_DEV_PORTS)
    if container_port not in ports:
        ports.append(container_port)
    return project_dev_port_map(project_dir, ports, project_name)[container_port]


def build_dev_mounts(
    project_dir: Path,
    project_name: str,
    extra_node_modules_paths: list[str] | None = None,
) -> list[Mount]:
    """Build the full mount list matching docker-compose.yml dev service.

    Required mounts are always included. Optional mounts are skipped
    if the source path doesn't exist on the host.

    *extra_node_modules_paths* is a list of glob patterns relative to
    *project_dir*. Each glob match (that is a directory) gets its own named
    volume overlaid at ``{match}/node_modules`` inside the container, so each
    workspace in a monorepo isolates its Linux node_modules from the host
    bind mount the same way the root overlay does.
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

    # Ensure directories that tools need for persistent config exist on the
    # host so bind mounts aren't silently skipped.
    for d in (".pi", ".augint", ".plannotator"):
        (home / d).mkdir(parents=True, exist_ok=True)

    # Zapier CLI auth is a single JSON file; pre-create it so the bind mount
    # exists and `zapier login` inside the container persists across
    # container recreations (mirrors the .claude.json single-file bind).
    zapierrc = home / ".zapierrc"
    if not zapierrc.exists():
        zapierrc.write_text("{}\n")

    # Optional bind mounts — skip if source doesn't exist
    optional_binds: list[tuple[Path, str, bool]] = [
        (home / ".config", "/root/.config", False),
        (home / ".codex", "/root/.codex", False),
        (home / ".claude", "/root/.claude", False),
        (home / ".claude.json", "/root/.claude.json", False),
        (home / ".pi", "/root/.pi", False),
        (home / ".augint", "/root/.augint", False),
        (home / ".plannotator", "/root/.plannotator", False),
        (home / ".zapierrc", "/root/.zapierrc", False),
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

    # Named volume: composer cache (shared across all projects). Without it
    # composer re-downloads every package on container recreation.
    mounts.append(
        Mount(
            target="/root/.cache/composer",
            source=COMPOSER_CACHE_VOLUME,
            type="volume",
        )
    )

    # Named volume: pnpm content-addressable store (shared across all
    # projects). Corepack's pnpm is container-local otherwise, so every
    # container rebuild is a cold install; the npm cache doesn't help pnpm.
    mounts.append(
        Mount(
            target="/root/.local/share/pnpm",
            source=PNPM_STORE_VOLUME,
            type="volume",
        )
    )

    # Named volume: pre-commit cache (shared across all projects).
    # Isolates the container's hook environments from the Windows host's
    # ~/.cache/pre-commit so the two installs don't clobber each other.
    mounts.append(
        Mount(
            target=PRE_COMMIT_CACHE_PATH,
            source=PRE_COMMIT_CACHE_VOLUME,
            type="volume",
        )
    )

    # Per-project named volume overlaying node_modules. Without this the
    # container's Linux `npm ci` would write into the bind-mounted host
    # project dir and collide with host-built (e.g. Windows) node_modules.
    # npm has no equivalent of UV_PROJECT_ENVIRONMENT, so we isolate at the
    # mount layer instead. Host node_modules underneath stays untouched.
    mounts.append(
        Mount(
            target=f"/root/projects/{project_name}/node_modules",
            source=node_modules_volume_name(project_name),
            type="volume",
        )
    )

    # Per-project named volume overlaying composer's vendor/ — the exact
    # node_modules rationale applies verbatim. Conditional on composer.json
    # so non-PHP projects don't grow an empty vendor/ dir on the host.
    if (project_dir / "composer.json").is_file():
        mounts.append(
            Mount(
                target=f"/root/projects/{project_name}/vendor",
                source=vendor_volume_name(project_name),
                type="volume",
            )
        )

    # Monorepo workspaces: overlay an isolated named volume on each matched
    # workspace's node_modules so per-app installs (npm/pnpm/yarn workspaces)
    # land in container-only storage rather than the host bind mount.
    project_root = project_dir.resolve()
    seen_targets: set[str] = {f"/root/projects/{project_name}/node_modules"}
    for pattern in extra_node_modules_paths or []:
        for match in sorted(project_root.glob(pattern)):
            if not match.is_dir():
                continue
            try:
                rel = match.relative_to(project_root)
            except ValueError:
                continue
            rel_posix = rel.as_posix()
            target = f"/root/projects/{project_name}/{rel_posix}/node_modules"
            if target in seen_targets:
                continue
            seen_targets.add(target)
            mounts.append(
                Mount(
                    target=target,
                    source=node_modules_volume_name(project_name, subpath=rel_posix),
                    type="volume",
                )
            )

    return mounts


def docker_tcp_fallback_host() -> str | None:
    """DOCKER_HOST value for dev containers when no Unix socket exists to mount.

    On Windows hosts there is no /var/run/docker.sock for build_dev_mounts to
    bind-mount, but Docker Desktop can expose the daemon on localhost:2375
    ("Expose daemon on tcp://localhost:2375 without TLS"). When that endpoint
    is reachable, containers reach the same daemon via host.docker.internal —
    return the DOCKER_HOST value to inject. Returns None when the socket
    mount already covers Docker access or no tcp endpoint is listening.
    """
    import socket

    if Path("/var/run/docker.sock").exists():
        return None
    try:
        with socket.create_connection(("localhost", 2375), timeout=1):
            pass
    except OSError:
        return None
    return "tcp://host.docker.internal:2375"


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


def _load_layered_dotenv(
    project_dir: Path | None = None,
    env_file: Path | None = None,
) -> dict[str, str | None]:
    """Load layered .env files.

    ``~/.augint/.env`` always loads (global augint suite config). The project
    ``./.env`` and explicit *env_file* only load when *env_file* is given
    (i.e. user passed ``--env`` on the CLI). Later layers override earlier
    ones.
    """
    from dotenv import dotenv_values

    layers: dict[str, str | None] = {}

    global_path = Path.home() / ".augint" / ".env"
    if global_path.is_file():
        layers.update(dotenv_values(global_path))

    if env_file is None:
        return layers

    if project_dir is not None:
        project_path = project_dir / ".env"
        if project_path.is_file() and project_path.resolve() != env_file.resolve():
            layers.update(dotenv_values(project_path))

    if env_file.is_file():
        layers.update(dotenv_values(env_file))

    return layers


_SHARED_ENV_PASSTHROUGH = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "PRIMARY_CHAT_MODEL",
    "SECONDARY_CHAT_MODEL",
    "PRIMARY_CODING_MODEL",
    "SECONDARY_CODING_MODEL",
    "CONTEXT_SIZE",
    "OLLAMA_PORT",
    "WEBUI_PORT",
    "KOKORO_PORT",
    "WHISPER_PORT",
    "N8N_PORT",
    "COMFYUI_PORT",
    "OPENCODE_SERVER_PASSWORD",
    "OPENCODE_SERVER_USERNAME",
    "PI_STUDIO_HOST",
)


def build_dev_environment(
    extra_env: dict[str, str] | None = None,
    project_dir: Path | None = None,
    *,
    project_name: str = "",
    bedrock: bool = False,
    aws_profile: str = "",
    aws_region: str = "",
    bedrock_profile: str = "",
    bedrock_region: str = "",
    openai_profile: str = "",
    team_mode: bool = False,
    env_file: Path | None = None,
) -> dict[str, str]:
    """Build environment variables matching docker-compose.yml dev service.

    ``~/.augint/.env`` always loads (global augint suite config). The project
    ``./.env`` only loads when *env_file* is given (``--env`` on the CLI);
    when loaded, **all** of its keys flow through to the container.

    Priority (highest wins): extra_env > CLI flags > ``./.env`` (when ``--env``)
    > ``~/.augint/.env`` > host ``os.environ`` (allowlisted) > defaults.

    GitHub auth defaults to SSO via the ``~/.config/gh`` bind mount. To use a
    PAT instead, put ``GH_TOKEN`` in ``.env`` and pass ``--env``.

    When *bedrock* is True, ``CLAUDE_CODE_USE_BEDROCK=1`` is injected and
    *bedrock_profile* (if set) overrides ``AWS_PROFILE`` so the LLM provider
    authenticates with the correct AWS account.

    When *openai_profile* is set, the suffixed env vars
    ``OPENAI_API_KEY_{NAME}`` and ``OPENAI_ORG_ID_{NAME}`` are resolved from
    ``.env`` and injected as ``OPENAI_API_KEY`` / ``OPENAI_ORG_ID``.

    When *team_mode* is True, ``CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`` is
    injected to enable Claude Code's Agent Teams feature.
    """
    dotenv = _load_layered_dotenv(project_dir, env_file=env_file)

    def _resolve(key: str, default: str = "") -> str:
        """Resolve a value: .env > os.environ > default."""
        dotenv_val = dotenv.get(key)
        if dotenv_val is not None and dotenv_val != "":
            return dotenv_val
        return os.environ.get(key, default)

    _CONTAINER_BASE_PATH = (
        "/root/.local/bin:/root/.opencode/bin:"
        "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    )

    env: dict[str, str] = {
        "PATH": _CONTAINER_BASE_PATH,
        "AWS_PROFILE": aws_profile or _resolve("AWS_PROFILE"),
        "AWS_REGION": aws_region or _resolve("AWS_REGION", "us-east-1"),
        "AWS_PAGER": "",
        "HUSKY": "0",
        "IS_SANDBOX": "1",
        "PRE_COMMIT_HOME": PRE_COMMIT_CACHE_PATH,
        "PI_STUDIO_HOST": "0.0.0.0",  # nosec B104
        "PLANNOTATOR_REMOTE": "1",
        "PLANNOTATOR_PORT": "19432",
        "PLANNOTATOR_BROWSER": "echo",
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
        resolved_bedrock_region = (
            bedrock_region or _resolve("AWS_BEDROCK_REGION") or env["AWS_REGION"]
        )
        if resolved_bedrock_region != env["AWS_REGION"]:
            env["AWS_REGION"] = resolved_bedrock_region
            env["AWS_DEFAULT_REGION"] = resolved_bedrock_region

    if openai_profile:
        suffix = openai_profile.upper()
        key_var = f"OPENAI_API_KEY_{suffix}"
        api_key = dotenv.get(key_var)
        if not api_key:
            raise ValueError(
                f"OpenAI profile '{openai_profile}' requires {key_var} in "
                "~/.augint/.env, or pass --env to load it from ./.env"
            )
        env["OPENAI_API_KEY"] = api_key
        org_var = f"OPENAI_ORG_ID_{suffix}"
        org_id = dotenv.get(org_var)
        if org_id:
            env["OPENAI_ORG_ID"] = org_id

    if team_mode:
        env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"

    for var in _SHARED_ENV_PASSTHROUGH:
        val = _resolve(var)
        if val:
            env[var] = val

    # Pass through every var loaded from .env, except keys already populated
    # above (which preserves CLI-flag wins for AWS_PROFILE etc.).
    for key, value in dotenv.items():
        if value is not None and value != "" and key not in env:
            env[key] = value

    if extra_env:
        env.update(extra_env)

    return env


def _resolve_env(dotenv: dict[str, str | None], key: str, default: str = "") -> str:
    """Resolve a value: dotenv > os.environ > default."""
    dotenv_val = dotenv.get(key)
    if dotenv_val is not None and dotenv_val != "":
        return dotenv_val
    return os.environ.get(key, default)


def build_n8n_environment(
    env_file: Path | None = None,
    *,
    aws_profile: str = "",
    aws_region: str = "",
) -> dict[str, str]:
    """Build environment variables for the n8n workflow automation container.

    Loads layered .env files (``~/.augint/.env`` then *env_file*),
    then falls back to host environment variables.

    Service discovery URLs use internal Docker network hostnames so n8n
    workflows can reference them via ``{{ $env.OLLAMA_BASE_URL }}`` etc.
    """
    dotenv = _load_layered_dotenv(env_file=env_file)

    env: dict[str, str] = {
        # Disable secure-cookie so the UI works over plain http://localhost.
        "N8N_SECURE_COOKIE": "false",
        # Service discovery (internal Docker network URLs).
        "OLLAMA_BASE_URL": f"http://{OLLAMA_CONTAINER}:11434",
        "KOKORO_BASE_URL": f"http://{KOKORO_CONTAINER}:8880",
        "WHISPER_BASE_URL": f"http://{WHISPER_CONTAINER}:8000",
        "VOICE_AGENT_BASE_URL": f"http://{VOICE_AGENT_CONTAINER}:8000",
        "WEBUI_BASE_URL": f"http://{WEBUI_CONTAINER}:8080",
        "COMFYUI_BASE_URL": f"http://{COMFYUI_CONTAINER}:8188",
    }

    # AWS credentials
    aws_prof = aws_profile or _resolve_env(dotenv, "AWS_PROFILE")
    aws_reg = aws_region or _resolve_env(dotenv, "AWS_REGION", "us-east-1")
    if aws_prof:
        env["AWS_PROFILE"] = aws_prof
    env["AWS_REGION"] = aws_reg
    env["AWS_DEFAULT_REGION"] = aws_reg

    # API keys — only include when non-empty.
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        val = _resolve_env(dotenv, key)
        if val:
            env[key] = val

    if env_file is not None:
        gh_token = _resolve_env(dotenv, "GH_TOKEN")
        if gh_token:
            env["GH_TOKEN"] = gh_token
            env["GITHUB_TOKEN"] = gh_token
            env["GITHUB_MODELS_BASE_URL"] = "https://models.inference.ai.azure.com"

    return env


def build_n8n_mounts(
    workflow_dir: Path | None = None,
) -> list[Mount]:
    """Build the mount list for the n8n container.

    n8n runs as user ``node`` (UID 1000).  Credential directories are mounted
    read-only under ``/home/node/`` so the AWS and GitHub CLIs resolve auth
    the same way the dev container does.
    """
    from docker.types import Mount

    home = Path.home()

    mounts: list[Mount] = [
        # Persistent data (workflows, credentials DB, settings).
        Mount(
            target="/home/node/.n8n",
            source=N8N_DATA_VOLUME,
            type="volume",
        ),
    ]

    # Optional credential bind mounts (read-only).
    aws_dir = home / ".aws"
    if aws_dir.exists():
        mounts.append(
            Mount(
                target="/home/node/.aws",
                source=str(aws_dir),
                type="bind",
                read_only=True,
            )
        )
    else:
        logger.debug("Skipping n8n AWS mount (not found): %s", aws_dir)

    gh_config = _find_gh_config_dir()
    if gh_config is not None:
        mounts.append(
            Mount(
                target="/home/node/.config/gh",
                source=str(gh_config),
                type="bind",
                read_only=True,
            )
        )

    # Starter workflow templates (read-only bind mount).
    if workflow_dir is not None and workflow_dir.is_dir():
        mounts.append(
            Mount(
                target="/workflows",
                source=str(workflow_dir),
                type="bind",
                read_only=True,
            )
        )

    return mounts
