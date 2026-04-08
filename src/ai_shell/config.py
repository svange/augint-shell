"""Configuration loading for ai-shell.

Priority (highest wins): CLI flags > env vars > project ai-shell.toml > global config > defaults.
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

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
    image_tag: str = __version__
    project_name: str = ""
    project_dir: Path = field(default_factory=Path.cwd)

    # LLM
    primary_model: str = DEFAULT_PRIMARY_MODEL
    fallback_model: str = DEFAULT_FALLBACK_MODEL
    context_size: int = DEFAULT_CONTEXT_SIZE
    ollama_port: int = DEFAULT_OLLAMA_PORT
    webui_port: int = DEFAULT_WEBUI_PORT

    # Aider
    aider_model: str = f"ollama_chat/{DEFAULT_PRIMARY_MODEL}"

    # Extra configuration
    extra_env: dict[str, str] = field(default_factory=dict)
    extra_volumes: list[str] = field(default_factory=list)
    extra_ports: list[int] = field(default_factory=list)

    # AWS
    ai_profile: str = ""  # AWS profile for infra (sets AWS_PROFILE in container)
    aws_region: str = ""  # Override AWS_REGION
    bedrock_profile: str = ""  # AWS profile for Bedrock LLM API calls

    # Per-tool provider
    claude_provider: str = ""  # "anthropic" (default) or "aws"
    opencode_provider: str = ""  # "local" (default, Ollama) or "aws" (Bedrock)
    codex_provider: str = ""  # "openai" (default) or "aws" (Bedrock)
    codex_openai_api_key: str = ""  # OpenAI API key (if set, overrides mounted SSO auth)
    codex_profile: str = ""  # AWS profile for Bedrock auth (when provider = "aws")

    # Project workflow
    repo_type: str | None = None  # "library" | "service" | "workspace"
    branch_strategy: str | None = None  # "main" | "dev"
    dev_branch: str = "dev"

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

    # Load global config
    global_config_path = Path.home() / ".config" / "ai-shell" / "config.toml"
    if global_config_path.exists():
        _apply_toml(config, global_config_path)

    # Load project config
    project_config_path = config.project_dir / ".ai-shell.toml"
    if project_config_path.exists():
        _apply_toml(config, project_config_path)

    # Apply environment variable overrides
    _apply_env_vars(config)

    # Apply CLI overrides
    if project_override:
        config.project_name = project_override

    # Auto-derive project name from CWD if not set
    if not config.project_name:
        from ai_shell.defaults import sanitize_project_name

        config.project_name = sanitize_project_name(config.project_dir)

    return config


def _apply_toml(config: AiShellConfig, path: Path) -> None:
    """Apply settings from a TOML config file."""
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
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

    # [aider] section
    aider = data.get("aider", {})
    if "model" in aider:
        config.aider_model = aider["model"]

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

    # [opencode] section
    opencode_sec = data.get("opencode", {})
    if "provider" in opencode_sec:
        config.opencode_provider = opencode_sec["provider"]

    # [codex] section
    codex_sec = data.get("codex", {})
    if "provider" in codex_sec:
        config.codex_provider = codex_sec["provider"]
    if "openai_api_key" in codex_sec:
        config.codex_openai_api_key = codex_sec["openai_api_key"]
    if "profile" in codex_sec:
        config.codex_profile = codex_sec["profile"]

    # [project] section
    project = data.get("project", {})
    if "repo_type" in project:
        config.repo_type = project["repo_type"]
    if "branch_strategy" in project:
        config.branch_strategy = project["branch_strategy"]
    if "dev_branch" in project:
        config.dev_branch = project["dev_branch"]


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
        "AI_SHELL_AIDER_MODEL": ("aider_model", str),
        "AI_SHELL_AI_PROFILE": ("ai_profile", str),
        "AI_SHELL_AWS_REGION": ("aws_region", str),
        "AI_SHELL_BEDROCK_PROFILE": ("bedrock_profile", str),
        "AI_SHELL_CLAUDE_PROVIDER": ("claude_provider", str),
        "AI_SHELL_OPENCODE_PROVIDER": ("opencode_provider", str),
        "AI_SHELL_CODEX_PROVIDER": ("codex_provider", str),
        "AI_SHELL_CODEX_OPENAI_API_KEY": ("codex_openai_api_key", str),
        "AI_SHELL_CODEX_PROFILE": ("codex_profile", str),
    }

    for env_key, (attr, type_fn) in env_map.items():
        value = os.environ.get(env_key)
        if value is not None:
            setattr(config, attr, type_fn(value))
            logger.debug("Config override from env: %s=%s", env_key, value)

    # AI_SHELL_PORTS is comma-separated, extends extra_ports
    ports_value = os.environ.get("AI_SHELL_PORTS")
    if ports_value:
        config.extra_ports.extend(int(p.strip()) for p in ports_value.split(",") if p.strip())
