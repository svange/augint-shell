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

logger = logging.getLogger(__name__)


@dataclass
class VoiceAgentModelProfile:
    """A named pair of primary + secondary chat models for the voice agent."""

    primary: str = ""
    secondary: str = ""


@dataclass
class VoiceAgentVadConfig:
    """Silero VAD / barge-in behavior."""

    silence_timeout_ms: int = 2500
    barge_in: bool = True


@dataclass
class VoiceAgentFilesystemConfig:
    """Filesystem tool scoping. Consumed by Phase 4."""

    root: str = "~/gigachad"
    read: list[str] = field(default_factory=lambda: ["~/gigachad"])
    write: list[str] = field(default_factory=lambda: ["~/gigachad"])
    deny_glob: list[str] = field(default_factory=lambda: ["**/.env*", "**/.git/**"])


@dataclass
class VoiceAgentMemoryConfig:
    """Sqlite memory behavior. Consumed by Phase 5."""

    enabled: bool = True
    summarize_after_turns: int = 20


@dataclass
class VoiceAgentAuthConfig:
    """App-level session auth. Consumed by Phase 3."""

    username: str = ""
    password_bcrypt: str = ""
    session_secret: str = ""


@dataclass
class VoiceAgentProvidersConfig:
    """LLM provider selection. Consumed by Phase 6."""

    default: str = "ollama"
    available: list[str] = field(default_factory=lambda: ["ollama"])


@dataclass
class VoiceAgentToolConfig:
    """A single tool entry under `voice_agent.tools`."""

    enabled: bool = False
    provider: str = ""


@dataclass
class VoiceAgentToolsConfig:
    """Tool registry. Consumed by Phase 4."""

    filesystem: VoiceAgentToolConfig = field(default_factory=VoiceAgentToolConfig)
    web_search: VoiceAgentToolConfig = field(
        default_factory=lambda: VoiceAgentToolConfig(provider="brave")
    )
    github: VoiceAgentToolConfig = field(default_factory=VoiceAgentToolConfig)


@dataclass
class VoiceAgentWakeWordConfig:
    """Wake-word gating. Consumed by Phase 3."""

    enabled: bool = False
    name: str = "hey_jarvis"


@dataclass
class VoiceAgentConfig:
    """Full voice-agent config tree.

    Phase 2 wires only ``port`` at the container layer. The remaining fields
    are schema placeholders for Phases 3-6 with reasonable defaults so early
    adopters can see the shape without the CLI refusing unknown keys.
    """

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
    vad: VoiceAgentVadConfig = field(default_factory=VoiceAgentVadConfig)
    filesystem: VoiceAgentFilesystemConfig = field(default_factory=VoiceAgentFilesystemConfig)
    memory: VoiceAgentMemoryConfig = field(default_factory=VoiceAgentMemoryConfig)
    auth: VoiceAgentAuthConfig = field(default_factory=VoiceAgentAuthConfig)
    providers: VoiceAgentProvidersConfig = field(default_factory=VoiceAgentProvidersConfig)
    tools: VoiceAgentToolsConfig = field(default_factory=VoiceAgentToolsConfig)
    wake_word: VoiceAgentWakeWordConfig = field(default_factory=VoiceAgentWakeWordConfig)


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
    # OpenCode / Aider. `extra_models` is a free-form list of additional
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

    # AWS
    ai_profile: str = ""  # AWS profile for infra (sets AWS_PROFILE in container)
    aws_region: str = ""  # Override AWS_REGION
    bedrock_profile: str = ""  # AWS profile for Bedrock LLM API calls
    bedrock_model: str = "us.meta.llama3-3-70b-instruct-v1:0"

    # OpenAI
    openai_profile: str = ""  # Suffixed .env key name for multi-account switching

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
    if "vad" in data and isinstance(data["vad"], dict):
        vad = data["vad"]
        if "silence_timeout_ms" in vad:
            va.vad.silence_timeout_ms = int(vad["silence_timeout_ms"])
        if "barge_in" in vad:
            va.vad.barge_in = bool(vad["barge_in"])
    if "filesystem" in data and isinstance(data["filesystem"], dict):
        fs = data["filesystem"]
        if "root" in fs:
            va.filesystem.root = str(fs["root"])
        if "read" in fs:
            va.filesystem.read = [str(p) for p in fs["read"]]
        if "write" in fs:
            va.filesystem.write = [str(p) for p in fs["write"]]
        if "deny_glob" in fs:
            va.filesystem.deny_glob = [str(p) for p in fs["deny_glob"]]
    if "memory" in data and isinstance(data["memory"], dict):
        mem = data["memory"]
        if "enabled" in mem:
            va.memory.enabled = bool(mem["enabled"])
        if "summarize_after_turns" in mem:
            va.memory.summarize_after_turns = int(mem["summarize_after_turns"])
    if "auth" in data and isinstance(data["auth"], dict):
        auth = data["auth"]
        if "username" in auth:
            va.auth.username = str(auth["username"])
        if "password_bcrypt" in auth:
            va.auth.password_bcrypt = str(auth["password_bcrypt"])
        if "session_secret" in auth:
            va.auth.session_secret = str(auth["session_secret"])
    if "providers" in data and isinstance(data["providers"], dict):
        providers = data["providers"]
        if "default" in providers:
            va.providers.default = str(providers["default"])
        if "available" in providers:
            va.providers.available = [str(p) for p in providers["available"]]
    if "tools" in data and isinstance(data["tools"], dict):
        tools = data["tools"]
        for tool_name in ("filesystem", "web_search", "github"):
            entry = tools.get(tool_name)
            if isinstance(entry, dict):
                tool = getattr(va.tools, tool_name)
                if "enabled" in entry:
                    tool.enabled = bool(entry["enabled"])
                if "provider" in entry:
                    tool.provider = str(entry["provider"])
    if "wake_word" in data and isinstance(data["wake_word"], dict):
        wake = data["wake_word"]
        if "enabled" in wake:
            va.wake_word.enabled = bool(wake["enabled"])
        if "name" in wake:
            va.wake_word.name = str(wake["name"])


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
    if "bedrock_profile" in aws:
        config.bedrock_profile = aws["bedrock_profile"]
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
    if "local_chrome" in claude_sec:
        config.local_chrome = bool(claude_sec["local_chrome"])
    if "pinned_image" in container:
        config.pinned_image = bool(container["pinned_image"])
    if "skip_updates" in container:
        config.skip_updates = bool(container["skip_updates"])


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
        "AI_SHELL_BEDROCK_PROFILE": ("bedrock_profile", str),
        "AI_SHELL_BEDROCK_MODEL": ("bedrock_model", str),
        "AI_SHELL_OPENAI_PROFILE": ("openai_profile", str),
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
