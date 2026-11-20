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

from ai_shell.defaults import (
    DEFAULT_COMFYUI_PORT,
    DEFAULT_CONTEXT_SIZE,
    DEFAULT_DEV_PORTS,
    DEFAULT_EXTRA_MODELS,
    DEFAULT_IMAGE,
    DEFAULT_KOKORO_PORT,
    DEFAULT_KOKORO_VOICE,
    DEFAULT_N8N_PORT,
    DEFAULT_OLLAMA_PORT,
    DEFAULT_PRIMARY_CHAT_MODEL,
    DEFAULT_PRIMARY_CODING_MODEL,
    DEFAULT_SECONDARY_CHAT_MODEL,
    DEFAULT_SECONDARY_CODING_MODEL,
    DEFAULT_VOICE_AGENT_PORT,
    DEFAULT_WEBUI_PORT,
    DEFAULT_WHISPER_MODEL,
    DEFAULT_WHISPER_PORT,
)
from ai_shell.opencode import CustomEndpoint, parse_endpoint_spec, sanitize_provider_id
from ai_shell.remote import RemoteBox

logger = logging.getLogger(__name__)


@dataclass
class VoiceAgentModelProfile:
    """A named pair of primary + secondary chat models for the voice agent."""

    primary: str = ""
    secondary: str = ""


@dataclass
class VoiceAgentConfig:
    """Voice-agent configuration."""

    port: int = DEFAULT_VOICE_AGENT_PORT
    domain: str = ""
    profile: str = "resident"
    profiles: dict[str, VoiceAgentModelProfile] = field(
        default_factory=lambda: {
            "resident": VoiceAgentModelProfile(
                primary="qwen3.5:9b",
                secondary="huihui_ai/qwen3.5-abliterated:9b",
            ),
            "swap": VoiceAgentModelProfile(
                primary="qwen3.5:27b",
                secondary="dolphin3:8b",
            ),
        }
    )


@dataclass
class AiShellConfig:
    """Configuration for ai-shell."""

    # Container
    image: str = DEFAULT_IMAGE
    image_tag: str = "latest"
    project_name: str = ""
    project_dir: Path = field(default_factory=Path.cwd)

    # LLM model slots. Primary = best-available; secondary = best uncensored
    # alternative. Chat slots are routed to Open WebUI, coding slots to
    # OpenCode. `extra_models` is a free-form list of additional
    # Ollama tags to pull alongside the 4 slots (deduped).
    primary_chat_model: str = DEFAULT_PRIMARY_CHAT_MODEL
    secondary_chat_model: str = DEFAULT_SECONDARY_CHAT_MODEL
    primary_coding_model: str = DEFAULT_PRIMARY_CODING_MODEL
    secondary_coding_model: str = DEFAULT_SECONDARY_CODING_MODEL
    extra_models: list[str] = field(default_factory=lambda: list(DEFAULT_EXTRA_MODELS))
    context_size: int = DEFAULT_CONTEXT_SIZE
    ollama_port: int = DEFAULT_OLLAMA_PORT
    webui_port: int = DEFAULT_WEBUI_PORT
    kokoro_port: int = DEFAULT_KOKORO_PORT
    kokoro_voice: str = DEFAULT_KOKORO_VOICE
    n8n_port: int = DEFAULT_N8N_PORT
    whisper_port: int = DEFAULT_WHISPER_PORT
    whisper_model: str = DEFAULT_WHISPER_MODEL
    comfyui_port: int = DEFAULT_COMFYUI_PORT

    # Voice agent (Phase 2 wires `port`; remaining fields are schema
    # placeholders that Phases 3-6 consume — see VoiceAgentConfig).
    voice_agent: VoiceAgentConfig = field(default_factory=VoiceAgentConfig)

    # Extra configuration
    extra_env: dict[str, str] = field(default_factory=dict)
    extra_volumes: list[str] = field(default_factory=list)
    extra_ports: list[int] = field(default_factory=list)
    # Glob patterns (relative to project_dir) for monorepo workspace
    # node_modules directories. Each match gets an isolated named volume.
    node_modules_paths: list[str] = field(default_factory=list)
    # Home-config basenames (e.g. ".claude", ".codex") to back with a shared
    # named volume instead of a host bind mount, so tool config/state never
    # touches the host home directory. Empty = current bind-mount behavior.
    isolate_home_paths: list[str] = field(default_factory=list)
    # False: no GitHub sign-in in the dev container (no ~/.config/gh mount, no
    # GH_TOKEN/GITHUB_TOKEN), for a box whose code must never reach GitHub.com.
    github_auth: bool = True
    # False: the host Docker socket is not mounted. With the socket, a process in
    # the container can start a container that mounts the whole host.
    docker_socket: bool = True
    # Dev container GUI forwarding (WSLg / X11 / Wayland + X11 TCP fallback)
    # and NVIDIA GPU passthrough (CUDA / model hosting).
    gui: bool = False
    gui_display: str = ""
    gpu: bool = False

    # AWS
    ai_profile: str = ""  # AWS profile for infra (sets AWS_PROFILE in container)
    aws_region: str = ""  # Override AWS_REGION
    aws_partition: str = ""  # "commercial" or "govcloud"
    bedrock_profile: str = ""  # AWS profile for Bedrock LLM API calls
    bedrock_region: str = ""  # AWS region for Bedrock (falls back to aws_region)
    bedrock_model: str = "us.meta.llama3-3-70b-instruct-v1:0"

    # OpenAI
    openai_profile: str = ""  # Suffixed .env key name for multi-account switching

    # Claude options
    claude_account: str = (
        ""  # Suffixed .env token name or login profile for multi-account switching
    )
    local_chrome: bool = False  # Attach Chrome DevTools MCP to project-scoped host Chrome
    chrome_proxy: str = (
        ""  # --proxy-server for every host Chrome ai-shell launches ("vpn" = own VPN)
    )
    skip_updates: bool = False
    background_updates: bool = True  # Run stale tool updates detached instead of blocking launch

    # VPN container (chrome_proxy: vpn). NordVPN over WireGuard through gluetun;
    # the credential is NORDVPN_TOKEN in ~/.augint/.env, never config.
    vpn_country: str = ""  # gluetun SERVER_COUNTRIES; empty = any server
    vpn_firewall: bool = True  # gluetun's own firewall; turned off by itself where it cannot run
    vpn_proxy_port: int = 8888  # loopback port of the HTTP proxy Chrome uses  # When True, skip pre-launch tool freshness checks

    # Expo. When False, a detected Expo app is not started automatically;
    # an explicit --expo still works. --expo/--no-expo override this.
    expo_auto: bool = True

    # Pre-launch image pull behavior and cache TTLs (seconds). Set TTL to 0 to disable.
    # "background" (default): launch immediately with local image, pull latest in a detached process.
    # "sync": block launch to pull latest when cache expires.
    # "manual": never auto-pull when a local image exists (use `ai-shell manage pull`).
    image_pull_mode: str = "background"
    image_pull_cache_ttl: int = 900  # 15 min: skip docker pull if checked recently
    bedrock_check_cache_ttl: int = 86400  # 24 h: skip Bedrock preflight if checked recently

    # Per-tool provider and OpenCode routing
    claude_provider: str = ""  # "anthropic" (default) or "aws"
    opencode_provider: str = (
        ""  # "ollama" (default), "aws" / "bedrock-mantle", or custom provider name
    )
    opencode_model: str = ""  # Primary model override for plan + build agents
    opencode_subagent_model: str = ""  # Subagent model override for explore + general agents
    opencode_endpoints: list[CustomEndpoint] = field(default_factory=list)
    # Off by default: OpenCode then reads AGENTS.md only, never CLAUDE.md,
    # ~/.claude or .claude/.agents skills.
    opencode_claude_compat: bool = False
    # None = the defaults in ai_shell.opencode; [] = none.
    opencode_plugins: list[str] | None = None
    opencode_instructions: list[str] | None = None
    opencode_local_chrome: bool = False  # Chrome DevTools MCP for ai-shell opencode
    # Bedrock region for ai-shell opencode only. Kept apart from bedrock_region
    # (Claude's) so a commercial default never reaches a GovCloud OpenCode.
    opencode_region: str = ""
    # `ai-shell opencode remote`: an OpenCode server on an EC2 box over SSM.
    opencode_remote: RemoteBox = field(default_factory=RemoteBox)

    @property
    def full_image(self) -> str:
        """Return the full image reference with tag."""
        return f"{self.image}:{self.image_tag}"

    @property
    def dev_ports(self) -> list[int]:
        """Return deduplicated, sorted list of dev container ports to expose."""
        return sorted(set(DEFAULT_DEV_PORTS + self.extra_ports))

    @property
    def models_to_pull(self) -> list[str]:
        """Return the full deduped list of Ollama model tags to pull.

        The 4 slots in order, followed by any ``extra_models``. Duplicates
        are removed while preserving first-occurrence order.
        """
        ordered = [
            self.primary_chat_model,
            self.secondary_chat_model,
            self.primary_coding_model,
            self.secondary_coding_model,
            *self.extra_models,
        ]
        seen: set[str] = set()
        deduped: list[str] = []
        for model in ordered:
            if model and model not in seen:
                seen.add(model)
                deduped.append(model)
        return deduped


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

    # Load global config (~/.augint/ canonical, ~/.ai-shell.yaml legacy fallback)
    home = Path.home()
    for candidate in (
        home / ".augint" / ".ai-shell.yaml",
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

    return config


def _load_config_file(path: Path) -> dict:
    """Load a YAML or TOML config file and return the parsed dict."""
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    with open(path, "rb") as f:
        return tomllib.load(f)


_LEGACY_LLM_KEY_HINT = {
    "primary_model": (
        "renamed to `primary_coding_model` (coding) or `primary_chat_model` "
        "(chat). The new config uses 4 role-specific slots; pick the one "
        "that matches your intent. See the generated .ai-shell.yaml for the "
        "full layout."
    ),
    "fallback_model": (
        "removed. The previous `fallback_model` was role-ambiguous. Use "
        "`secondary_chat_model` and `secondary_coding_model` instead "
        "(both default to the best uncensored variants). See the generated "
        ".ai-shell.yaml for the full layout."
    ),
}


def _reject_legacy_llm_keys(llm_section: dict, path: Path) -> None:
    """Raise on deprecated `primary_model` / `fallback_model` keys.

    These were removed when the llm config split into 4 role-specific slots
    (primary/secondary x chat/coding). Silently aliasing them would corrupt
    intent — e.g. the old `fallback_model` meant different things to chat and
    coding users. Fail loudly with migration guidance.
    """
    bad = [k for k in _LEGACY_LLM_KEY_HINT if k in llm_section]
    if not bad:
        return
    lines = [f"\nDeprecated llm key(s) found in {path}:"]
    for key in bad:
        lines.append(f"  - `{key}`: {_LEGACY_LLM_KEY_HINT[key]}")
    raise ValueError("\n".join(lines))


def _apply_voice_agent_config(va: VoiceAgentConfig, data: dict) -> None:
    """Merge a parsed ``voice_agent:`` section into a VoiceAgentConfig.

    Only keys present in *data* override defaults; everything else keeps
    the dataclass default. Nested sections are merged field-by-field so
    partial user configs work.
    """
    if "port" in data:
        va.port = int(data["port"])
    if "domain" in data:
        va.domain = str(data["domain"])
    if "profile" in data:
        va.profile = str(data["profile"])
    if "profiles" in data and isinstance(data["profiles"], dict):
        for name, entry in data["profiles"].items():
            profile = va.profiles.get(name, VoiceAgentModelProfile())
            if isinstance(entry, dict):
                if "primary" in entry:
                    profile.primary = str(entry["primary"])
                if "secondary" in entry:
                    profile.secondary = str(entry["secondary"])
            va.profiles[name] = profile


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
    if "node_modules_paths" in container:
        config.node_modules_paths.extend(str(p) for p in container["node_modules_paths"])
    if "isolate_home_paths" in container:
        config.isolate_home_paths.extend(str(p) for p in container["isolate_home_paths"])
    if "github_auth" in container:
        config.github_auth = bool(container["github_auth"])
    if "docker_socket" in container:
        config.docker_socket = bool(container["docker_socket"])
    if "gui" in container:
        config.gui = bool(container["gui"])
    if "gui_display" in container:
        config.gui_display = str(container["gui_display"])
    if "gpu" in container:
        config.gpu = bool(container["gpu"])

    # [expo] section
    expo = data.get("expo", {})
    if "auto" in expo:
        config.expo_auto = bool(expo["auto"])

    # [llm] section
    llm = data.get("llm", {})
    _reject_legacy_llm_keys(llm, path)
    if "primary_chat_model" in llm:
        config.primary_chat_model = llm["primary_chat_model"]
    if "secondary_chat_model" in llm:
        config.secondary_chat_model = llm["secondary_chat_model"]
    if "primary_coding_model" in llm:
        config.primary_coding_model = llm["primary_coding_model"]
    if "secondary_coding_model" in llm:
        config.secondary_coding_model = llm["secondary_coding_model"]
    if "extra_models" in llm:
        config.extra_models = [str(m) for m in llm["extra_models"]]
    if "context_size" in llm:
        config.context_size = int(llm["context_size"])
    if "ollama_port" in llm:
        config.ollama_port = int(llm["ollama_port"])
    if "webui_port" in llm:
        config.webui_port = int(llm["webui_port"])
    if "kokoro_port" in llm:
        config.kokoro_port = int(llm["kokoro_port"])
    if "kokoro_voice" in llm:
        config.kokoro_voice = str(llm["kokoro_voice"])
    if "n8n_port" in llm:
        config.n8n_port = int(llm["n8n_port"])
    if "whisper_port" in llm:
        config.whisper_port = int(llm["whisper_port"])
    if "whisper_model" in llm:
        config.whisper_model = str(llm["whisper_model"])
    if "comfyui_port" in llm:
        config.comfyui_port = int(llm["comfyui_port"])

    # [voice_agent] section (top-level, not under llm)
    if "voice_agent" in data:
        _apply_voice_agent_config(config.voice_agent, data["voice_agent"])

    # [aws] section
    aws = data.get("aws", {})
    if "ai_profile" in aws:
        config.ai_profile = aws["ai_profile"]
    if "region" in aws:
        config.aws_region = aws["region"]
    if "partition" in aws:
        config.aws_partition = str(aws["partition"] or "")
    if "aws_partition" in aws:
        config.aws_partition = str(aws["aws_partition"] or "")
    if "bedrock_profile" in aws:
        config.bedrock_profile = aws["bedrock_profile"]
    if "bedrock_region" in aws:
        config.bedrock_region = aws["bedrock_region"]
    if "bedrock_model" in aws:
        config.bedrock_model = aws["bedrock_model"]

    # [openai] section
    openai = data.get("openai", {})
    if "profile" in openai:
        config.openai_profile = openai["profile"]

    # [claude] section
    claude_sec = data.get("claude", {})
    if "provider" in claude_sec:
        config.claude_provider = claude_sec["provider"]
    if "account" in claude_sec:
        config.claude_account = str(claude_sec["account"])
    if "local_chrome" in claude_sec:
        config.local_chrome = bool(claude_sec["local_chrome"])
    if "chrome_proxy" in claude_sec:
        config.chrome_proxy = str(claude_sec["chrome_proxy"] or "")

    # [opencode] section
    opencode_sec = data.get("opencode", {})
    if isinstance(opencode_sec, dict):
        _apply_opencode_config(config, opencode_sec)

    # [vpn] section
    vpn = data.get("vpn", {})
    if isinstance(vpn, dict):
        if "country" in vpn:
            config.vpn_country = str(vpn["country"] or "")
        if "firewall" in vpn:
            config.vpn_firewall = bool(vpn["firewall"])
        if "proxy_port" in vpn:
            config.vpn_proxy_port = int(vpn["proxy_port"])
    if "skip_updates" in container:
        config.skip_updates = bool(container["skip_updates"])
    if "background_updates" in container:
        config.background_updates = bool(container["background_updates"])
    if "image_pull_mode" in container:
        config.image_pull_mode = _validate_image_pull_mode(str(container["image_pull_mode"]))
    if "image_pull_cache_ttl" in container:
        config.image_pull_cache_ttl = int(container["image_pull_cache_ttl"])
    if "bedrock_check_cache_ttl" in aws:
        config.bedrock_check_cache_ttl = int(aws["bedrock_check_cache_ttl"])


IMAGE_PULL_MODES: tuple[str, ...] = ("background", "sync", "manual")


def _validate_image_pull_mode(raw: str) -> str:
    """Normalize and validate ``container.image_pull_mode``."""
    mode = raw.strip().lower()
    if mode not in IMAGE_PULL_MODES:
        allowed = ", ".join(IMAGE_PULL_MODES)
        raise ValueError(f"Invalid image_pull_mode {raw!r}; expected one of: {allowed}")
    return mode


def _upsert_custom_endpoint(
    endpoints: list[CustomEndpoint],
    new_ep: CustomEndpoint,
) -> None:
    """Insert or replace a CustomEndpoint by provider name."""
    for idx, existing in enumerate(endpoints):
        if existing.name == new_ep.name:
            endpoints[idx] = new_ep
            return
    endpoints.append(new_ep)


def _coerce_models_list(raw: object) -> list[str]:
    """Normalize a string or list of model IDs into a list of non-empty strings."""
    if isinstance(raw, str):
        return [m.strip() for m in raw.split(",") if m.strip()]
    if isinstance(raw, list):
        return [str(m).strip() for m in raw if str(m).strip()]
    return []


def _parse_opencode_endpoints(raw: object) -> list[CustomEndpoint]:
    """Parse ``opencode.endpoints`` from YAML/TOML (supports dict or list formats)."""
    parsed: list[CustomEndpoint] = []
    if isinstance(raw, dict):
        for name, entry in raw.items():
            provider_id = sanitize_provider_id(str(name))
            if isinstance(entry, str) and entry.strip():
                parsed.append(CustomEndpoint(name=provider_id, base_url=entry.strip()))
            elif isinstance(entry, dict):
                base_url = str(entry.get("base_url") or entry.get("url") or "").strip()
                if not base_url:
                    continue
                api_key_env = str(entry.get("api_key_env") or entry.get("key_env") or "").strip()
                models_raw = entry.get("models") if "models" in entry else entry.get("model", [])
                models = _coerce_models_list(models_raw)
                display_name = str(entry.get("display_name") or "").strip()
                parsed.append(
                    CustomEndpoint(
                        name=provider_id,
                        base_url=base_url,
                        api_key_env=api_key_env,
                        models=models,
                        display_name=display_name,
                    )
                )
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.strip():
                parsed.append(parse_endpoint_spec(item))
            elif isinstance(item, dict):
                name = sanitize_provider_id(str(item.get("name") or "custom"))
                base_url = str(item.get("base_url") or item.get("url") or "").strip()
                if not base_url:
                    continue
                api_key_env = str(item.get("api_key_env") or item.get("key_env") or "").strip()
                models_raw = item.get("models") if "models" in item else item.get("model", [])
                models = _coerce_models_list(models_raw)
                display_name = str(item.get("display_name") or "").strip()
                parsed.append(
                    CustomEndpoint(
                        name=name,
                        base_url=base_url,
                        api_key_env=api_key_env,
                        models=models,
                        display_name=display_name,
                    )
                )
    return parsed


def _apply_opencode_config(config: AiShellConfig, data: dict) -> None:
    """Apply settings from the ``opencode:`` config section."""
    if "provider" in data:
        config.opencode_provider = str(data["provider"] or "")
    if "aws_partition" in data:
        config.aws_partition = str(data["aws_partition"] or "")
    elif "partition" in data:
        config.aws_partition = str(data["partition"] or "")
    if "aws_region" in data:
        config.opencode_region = str(data["aws_region"] or "")
    elif "region" in data:
        config.opencode_region = str(data["region"] or "")
    if "aws_profile" in data:
        config.bedrock_profile = str(data["aws_profile"] or "")
    elif "profile" in data:
        config.bedrock_profile = str(data["profile"] or "")
    if "model" in data:
        config.opencode_model = str(data["model"] or "")
    elif "primary_model" in data:
        config.opencode_model = str(data["primary_model"] or "")
    if "subagent_model" in data:
        config.opencode_subagent_model = str(data["subagent_model"] or "")
    if "endpoints" in data:
        for ep in _parse_opencode_endpoints(data["endpoints"]):
            _upsert_custom_endpoint(config.opencode_endpoints, ep)
    if "claude_compat" in data:
        config.opencode_claude_compat = bool(data["claude_compat"])
    if "plugins" in data:
        config.opencode_plugins = _string_list(data["plugins"])
    if "instructions" in data:
        config.opencode_instructions = _string_list(data["instructions"])
    if "local_chrome" in data:
        config.opencode_local_chrome = bool(data["local_chrome"])
    if isinstance(data.get("remote"), dict):
        config.opencode_remote = RemoteBox.from_dict(data["remote"])


def _string_list(raw: object) -> list[str]:
    """A config list of strings; ``None`` or an empty value is ``[]``."""
    if raw is None or raw == "":
        return []
    items = raw if isinstance(raw, list) else [raw]
    return [str(item).strip() for item in items if str(item).strip()]


_LEGACY_ENV_VARS = {
    "AI_SHELL_PRIMARY_MODEL": ("AI_SHELL_PRIMARY_CODING_MODEL or AI_SHELL_PRIMARY_CHAT_MODEL"),
    "AI_SHELL_FALLBACK_MODEL": ("AI_SHELL_SECONDARY_CHAT_MODEL or AI_SHELL_SECONDARY_CODING_MODEL"),
}


def _apply_env_vars(config: AiShellConfig) -> None:
    """Apply AI_SHELL_* environment variable overrides."""
    bad_env = [k for k in _LEGACY_ENV_VARS if os.environ.get(k) is not None]
    if bad_env:
        lines = ["\nDeprecated AI_SHELL_* env var(s) set:"]
        for key in bad_env:
            lines.append(f"  - {key}: use {_LEGACY_ENV_VARS[key]} instead")
        raise ValueError("\n".join(lines))

    env_map: dict[str, tuple[str, type]] = {
        "AI_SHELL_IMAGE": ("image", str),
        "AI_SHELL_IMAGE_TAG": ("image_tag", str),
        "AI_SHELL_PROJECT": ("project_name", str),
        "AI_SHELL_PRIMARY_CHAT_MODEL": ("primary_chat_model", str),
        "AI_SHELL_SECONDARY_CHAT_MODEL": ("secondary_chat_model", str),
        "AI_SHELL_PRIMARY_CODING_MODEL": ("primary_coding_model", str),
        "AI_SHELL_SECONDARY_CODING_MODEL": ("secondary_coding_model", str),
        "AI_SHELL_CONTEXT_SIZE": ("context_size", int),
        "AI_SHELL_OLLAMA_PORT": ("ollama_port", int),
        "AI_SHELL_WEBUI_PORT": ("webui_port", int),
        "AI_SHELL_KOKORO_PORT": ("kokoro_port", int),
        "AI_SHELL_KOKORO_VOICE": ("kokoro_voice", str),
        "AI_SHELL_N8N_PORT": ("n8n_port", int),
        "AI_SHELL_WHISPER_PORT": ("whisper_port", int),
        "AI_SHELL_WHISPER_MODEL": ("whisper_model", str),
        "AI_SHELL_COMFYUI_PORT": ("comfyui_port", int),
        "AI_SHELL_AI_PROFILE": ("ai_profile", str),
        "AI_SHELL_AWS_REGION": ("aws_region", str),
        "AI_SHELL_AWS_PARTITION": ("aws_partition", str),
        "AI_SHELL_BEDROCK_PROFILE": ("bedrock_profile", str),
        "AI_SHELL_BEDROCK_REGION": ("bedrock_region", str),
        "AI_SHELL_BEDROCK_MODEL": ("bedrock_model", str),
        "AI_SHELL_OPENAI_PROFILE": ("openai_profile", str),
        "AI_SHELL_CLAUDE_PROVIDER": ("claude_provider", str),
        "AI_SHELL_CLAUDE_ACCOUNT": ("claude_account", str),
        "AI_SHELL_OPENCODE_PROVIDER": ("opencode_provider", str),
        "AI_SHELL_OPENCODE_MODEL": ("opencode_model", str),
        "AI_SHELL_OPENCODE_SUBAGENT_MODEL": ("opencode_subagent_model", str),
        "AI_SHELL_OPENCODE_AWS_PARTITION": ("aws_partition", str),
        "AI_SHELL_OPENCODE_AWS_REGION": ("opencode_region", str),
        "AI_SHELL_OPENCODE_CLAUDE_COMPAT": ("opencode_claude_compat", bool),
        "AI_SHELL_OPENCODE_LOCAL_CHROME": ("opencode_local_chrome", bool),
        "AI_SHELL_LOCAL_CHROME": ("local_chrome", bool),
        "AI_SHELL_CHROME_PROXY": ("chrome_proxy", str),
        "AI_SHELL_VPN_COUNTRY": ("vpn_country", str),
        "AI_SHELL_VPN_FIREWALL": ("vpn_firewall", bool),
        "AI_SHELL_VPN_PROXY_PORT": ("vpn_proxy_port", int),
        "AI_SHELL_EXPO_AUTO": ("expo_auto", bool),
        "AI_SHELL_GUI": ("gui", bool),
        "AI_SHELL_GUI_DISPLAY": ("gui_display", str),
        "AI_SHELL_GPU": ("gpu", bool),
        "AI_SHELL_SKIP_UPDATES": ("skip_updates", bool),
        "AI_SHELL_BACKGROUND_UPDATES": ("background_updates", bool),
        "AI_SHELL_IMAGE_PULL_CACHE_TTL": ("image_pull_cache_ttl", int),
        "AI_SHELL_BEDROCK_CHECK_CACHE_TTL": ("bedrock_check_cache_ttl", int),
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

    image_pull_mode_val = os.environ.get("AI_SHELL_IMAGE_PULL_MODE")
    if image_pull_mode_val is not None:
        config.image_pull_mode = _validate_image_pull_mode(image_pull_mode_val)
        logger.debug("Config override from env: AI_SHELL_IMAGE_PULL_MODE=%s", image_pull_mode_val)

    # AI_SHELL_PORTS is comma-separated, extends extra_ports
    ports_value = os.environ.get("AI_SHELL_PORTS")
    if ports_value:
        config.extra_ports.extend(int(p.strip()) for p in ports_value.split(",") if p.strip())

    # AI_SHELL_ISOLATE_HOME_PATHS is comma-separated, extends isolate_home_paths
    isolate_value = os.environ.get("AI_SHELL_ISOLATE_HOME_PATHS")
    if isolate_value:
        config.isolate_home_paths.extend(p.strip() for p in isolate_value.split(",") if p.strip())

    # OpenCode custom endpoint env vars:
    # - AI_SHELL_OPENCODE_ENDPOINT / AI_SHELL_OPENCODE_ENDPOINTS (semicolon-separated specs)
    # - AI_SHELL_OPENCODE_CUSTOM_URL (+ optional _NAME, _KEY_ENV, _MODEL)
    for env_key in ("AI_SHELL_OPENCODE_ENDPOINT", "AI_SHELL_OPENCODE_ENDPOINTS"):
        raw_specs = os.environ.get(env_key, "").strip()
        if raw_specs:
            for spec in raw_specs.split(";"):
                if spec.strip():
                    _upsert_custom_endpoint(
                        config.opencode_endpoints,
                        parse_endpoint_spec(spec.strip()),
                    )

    custom_url = os.environ.get("AI_SHELL_OPENCODE_CUSTOM_URL", "").strip()
    if custom_url:
        custom_name = sanitize_provider_id(
            os.environ.get("AI_SHELL_OPENCODE_CUSTOM_NAME", "custom")
        )
        custom_key_env = os.environ.get("AI_SHELL_OPENCODE_CUSTOM_KEY_ENV", "").strip()
        custom_model_raw = os.environ.get("AI_SHELL_OPENCODE_CUSTOM_MODEL", "").strip()
        custom_models = [m.strip() for m in custom_model_raw.split(",") if m.strip()]
        _upsert_custom_endpoint(
            config.opencode_endpoints,
            CustomEndpoint(
                name=custom_name,
                base_url=custom_url,
                api_key_env=custom_key_env,
                models=custom_models,
            ),
        )

    # Nested voice_agent overrides (flat env vars map to nested fields)
    voice_agent_port = os.environ.get("AI_SHELL_VOICE_AGENT_PORT")
    if voice_agent_port is not None:
        config.voice_agent.port = int(voice_agent_port)
    voice_agent_domain = os.environ.get("AI_SHELL_VOICE_AGENT_DOMAIN")
    if voice_agent_domain is not None:
        config.voice_agent.domain = voice_agent_domain
    voice_agent_profile = os.environ.get("AI_SHELL_VOICE_AGENT_PROFILE")
    if voice_agent_profile is not None:
        config.voice_agent.profile = voice_agent_profile
