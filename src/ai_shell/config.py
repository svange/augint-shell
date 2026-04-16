"""Configuration loading for ai-shell.

Priority (highest wins): CLI flags > env vars > project config > global config > defaults.

Global config lookup order (first match wins):
  ~/.ai-shell.yaml > ~/.ai-shell.yml > ~/.ai-shell.toml
  > ~/.config/ai-shell/config.yaml > ~/.config/ai-shell/config.yml > ~/.config/ai-shell/config.toml

Project config lookup order (first match wins):
  .ai-shell.yaml > .ai-shell.yml > .ai-shell.toml > ai-shell.toml
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ai_shell import __version__
from ai_shell.defaults import (
    DEFAULT_CONTEXT_SIZE,
    DEFAULT_DEV_PORTS,
    DEFAULT_FALLBACK_MODEL,
    DEFAULT_IMAGE,
    DEFAULT_OLLAMA_PORT,
    DEFAULT_PRIMARY_MODEL,
    DEFAULT_WEBUI_PORT,
)

logger = logging.getLogger(__name__)


@dataclass
class AiShellConfig:
    """Configuration for ai-shell."""

    # Container
    image: str = DEFAULT_IMAGE
    image_tag: str = "latest"
    project_name: str = ""
    project_dir: Path = field(default_factory=Path.cwd)

    # LLM
    primary_model: str = DEFAULT_PRIMARY_MODEL
    fallback_model: str = DEFAULT_FALLBACK_MODEL
    context_size: int = DEFAULT_CONTEXT_SIZE
    ollama_port: int = DEFAULT_OLLAMA_PORT
    webui_port: int = DEFAULT_WEBUI_PORT

    # Extra configuration
    extra_env: dict[str, str] = field(default_factory=dict)
    extra_volumes: list[str] = field(default_factory=list)
    extra_ports: list[int] = field(default_factory=list)

    # AWS
    ai_profile: str = ""  # AWS profile for infra (sets AWS_PROFILE in container)
    aws_region: str = ""  # Override AWS_REGION
    bedrock_profile: str = ""  # AWS profile for Bedrock LLM API calls

    # Claude options
    local_chrome: bool = False  # Attach Chrome DevTools MCP to project-scoped host Chrome
    pinned_image: bool = False  # When True, use version-matched image tag instead of latest
    skip_updates: bool = False  # When True, skip pre-launch tool freshness checks

    # Per-tool provider
    claude_provider: str = ""  # "anthropic" (default) or "aws"

    @property
    def full_image(self) -> str:
        """Return the full image reference with tag."""
        return f"{self.image}:{self.image_tag}"

    @property
    def dev_ports(self) -> list[int]:
        """Return deduplicated, sorted list of dev container ports to expose."""
        return sorted(set(DEFAULT_DEV_PORTS + self.extra_ports))


def load_config(
    project_override: str | None = None,
    project_dir: Path | None = None,
) -> AiShellConfig:
    """Load configuration from all sources.

    Priority: CLI overrides > env vars > project toml > global toml > defaults.
    """
    config = AiShellConfig()

    if project_dir:
        config.project_dir = project_dir

    # Load global config (~/.ai-shell.yaml first, ~/.config/ai-shell/ as fallback)
    home = Path.home()
    for candidate in (
        home / ".ai-shell.yaml",
        home / ".ai-shell.yml",
        home / ".ai-shell.toml",
        home / ".config" / "ai-shell" / "config.yaml",
        home / ".config" / "ai-shell" / "config.yml",
        home / ".config" / "ai-shell" / "config.toml",
    ):
        if candidate.exists():
            _apply_config(config, candidate)
            break

    # Load project config (first match wins)
    for name in (".ai-shell.yaml", ".ai-shell.yml", ".ai-shell.toml", "ai-shell.toml"):
        candidate = config.project_dir / name
        if candidate.exists():
            _apply_config(config, candidate)
            break

    # Apply environment variable overrides
    _apply_env_vars(config)

    # Apply CLI overrides
    if project_override:
        config.project_name = project_override

    # Auto-derive project name from CWD if not set
    if not config.project_name:
        from ai_shell.defaults import sanitize_project_name

        config.project_name = sanitize_project_name(config.project_dir)

    # Pin to version-matched tag when pinned_image is set and tag wasn't
    # explicitly overridden to something other than the default "latest".
    if config.pinned_image and config.image_tag == "latest":
        config.image_tag = __version__

    return config


def _load_config_file(path: Path) -> dict:
    """Load a YAML or TOML config file and return the parsed dict."""
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _apply_config(config: AiShellConfig, path: Path) -> None:
    """Apply settings from a YAML or TOML config file."""
    try:
        data = _load_config_file(path)
    except (OSError, tomllib.TOMLDecodeError, yaml.YAMLError) as e:
        logger.warning("Failed to load config from %s: %s", path, e)
        return

    logger.debug("Loading config from %s", path)

    # [container] section
    container = data.get("container", {})
    if "image" in container:
        config.image = container["image"]
    if "image_tag" in container:
        config.image_tag = container["image_tag"]
    if "extra_env" in container:
        config.extra_env.update(container["extra_env"])
    if "extra_volumes" in container:
        config.extra_volumes.extend(container["extra_volumes"])
    if "ports" in container:
        config.extra_ports.extend(int(p) for p in container["ports"])

    # [llm] section
    llm = data.get("llm", {})
    if "primary_model" in llm:
        config.primary_model = llm["primary_model"]
    if "fallback_model" in llm:
        config.fallback_model = llm["fallback_model"]
    if "context_size" in llm:
        config.context_size = int(llm["context_size"])
    if "ollama_port" in llm:
        config.ollama_port = int(llm["ollama_port"])
    if "webui_port" in llm:
        config.webui_port = int(llm["webui_port"])

    # [aws] section
    aws = data.get("aws", {})
    if "ai_profile" in aws:
        config.ai_profile = aws["ai_profile"]
    if "region" in aws:
        config.aws_region = aws["region"]
    if "bedrock_profile" in aws:
        config.bedrock_profile = aws["bedrock_profile"]

    # [claude] section
    claude_sec = data.get("claude", {})
    if "provider" in claude_sec:
        config.claude_provider = claude_sec["provider"]
    if "local_chrome" in claude_sec:
        config.local_chrome = bool(claude_sec["local_chrome"])
    if "pinned_image" in container:
        config.pinned_image = bool(container["pinned_image"])
    if "skip_updates" in container:
        config.skip_updates = bool(container["skip_updates"])


def _apply_env_vars(config: AiShellConfig) -> None:
    """Apply AI_SHELL_* environment variable overrides."""
    env_map: dict[str, tuple[str, type]] = {
        "AI_SHELL_IMAGE": ("image", str),
        "AI_SHELL_IMAGE_TAG": ("image_tag", str),
        "AI_SHELL_PROJECT": ("project_name", str),
        "AI_SHELL_PRIMARY_MODEL": ("primary_model", str),
        "AI_SHELL_FALLBACK_MODEL": ("fallback_model", str),
        "AI_SHELL_CONTEXT_SIZE": ("context_size", int),
        "AI_SHELL_OLLAMA_PORT": ("ollama_port", int),
        "AI_SHELL_WEBUI_PORT": ("webui_port", int),
        "AI_SHELL_AI_PROFILE": ("ai_profile", str),
        "AI_SHELL_AWS_REGION": ("aws_region", str),
        "AI_SHELL_BEDROCK_PROFILE": ("bedrock_profile", str),
        "AI_SHELL_CLAUDE_PROVIDER": ("claude_provider", str),
        "AI_SHELL_LOCAL_CHROME": ("local_chrome", bool),
        "AI_SHELL_PINNED_IMAGE": ("pinned_image", bool),
        "AI_SHELL_SKIP_UPDATES": ("skip_updates", bool),
    }

    for env_key, (attr, type_fn) in env_map.items():
        value = os.environ.get(env_key)
        if value is not None:
            if type_fn is bool:
                coerced = value.lower() not in ("0", "false", "no", "")
            else:
                coerced = type_fn(value)
            setattr(config, attr, coerced)
            logger.debug("Config override from env: %s=%s", env_key, value)

    # AI_SHELL_PORTS is comma-separated, extends extra_ports
    ports_value = os.environ.get("AI_SHELL_PORTS")
    if ports_value:
        config.extra_ports.extend(int(p.strip()) for p in ports_value.split(",") if p.strip())
