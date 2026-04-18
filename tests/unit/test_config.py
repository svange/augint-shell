"""Tests for ai_shell.config module."""

from unittest.mock import patch

import pytest

from ai_shell.config import AiShellConfig, load_config
from ai_shell.defaults import DEFAULT_DEV_PORTS


class TestAiShellConfig:
    def test_defaults(self):
        config = AiShellConfig()
        assert config.image == "svange/augint-shell"
        assert config.primary_chat_model == "qwen3.5:27b"
        assert config.secondary_chat_model == "huihui_ai/qwen3.5-abliterated:27b"
        assert config.primary_coding_model == "qwen3-coder:30b-a3b-q4_K_M"
        assert (
            config.secondary_coding_model
            == "huihui_ai/qwen3-coder-abliterated:30b-a3b-instruct-q4_K_M"
        )
        assert config.extra_models == []
        assert config.ollama_port == 11434
        assert config.webui_port == 3000
        assert config.kokoro_port == 8880
        assert config.n8n_port == 5678
        assert config.whisper_port == 8001
        assert config.comfyui_port == 8188
        assert config.whisper_model == "Systran/faster-distil-whisper-large-v3"
        # Voice-agent defaults (Phase 2 wires only `port`; tree is present
        # for future phases).
        assert config.voice_agent.port == 8010
        assert config.voice_agent.profile == "resident"
        assert config.voice_agent.profiles["resident"].primary == "qwen3.5:14b-instruct"
        assert config.voice_agent.vad.silence_timeout_ms == 2500
        assert config.voice_agent.vad.barge_in is True
        assert config.voice_agent.wake_word.enabled is False
        assert config.voice_agent.providers.default == "ollama"
        assert config.voice_agent.tools.web_search.provider == "brave"

    def test_models_to_pull_dedupes_slots(self):
        # Same tag in primary and extras should dedupe to one entry.
        config = AiShellConfig(
            primary_chat_model="foo:1",
            secondary_chat_model="bar:1",
            primary_coding_model="foo:1",  # duplicates primary chat
            secondary_coding_model="baz:1",
            extra_models=["bar:1", "qux:1"],  # bar duplicates secondary chat
        )
        assert config.models_to_pull == ["foo:1", "bar:1", "baz:1", "qux:1"]

    def test_models_to_pull_skips_empty(self):
        config = AiShellConfig(
            primary_chat_model="foo:1",
            secondary_chat_model="",
            primary_coding_model="bar:1",
            secondary_coding_model="",
        )
        assert config.models_to_pull == ["foo:1", "bar:1"]

    def test_full_image(self):
        config = AiShellConfig(image="svange/augint-shell", image_tag="1.2.3")
        assert config.full_image == "svange/augint-shell:1.2.3"


class TestLoadConfig:
    def test_loads_defaults_when_no_files(self, tmp_path):
        config = load_config(project_dir=tmp_path)
        assert config.image == "svange/augint-shell"
        assert config.project_dir == tmp_path

    def test_auto_derives_project_name(self, tmp_path):
        project_dir = tmp_path / "my-cool-project"
        project_dir.mkdir()
        config = load_config(project_dir=project_dir)
        assert config.project_name == "my-cool-project"

    def test_project_override(self, tmp_path):
        config = load_config(project_override="custom-name", project_dir=tmp_path)
        assert config.project_name == "custom-name"

    def test_project_toml_loaded(self, tmp_path):
        toml_content = b"""
[container]
image = "custom/image"
image_tag = "2.0.0"

[llm]
primary_chat_model = "llama3:8b"
secondary_chat_model = "llama3:8b-uncensored"
primary_coding_model = "qwen-coder:test"
secondary_coding_model = "qwen-coder-uncensored:test"
extra_models = ["dolphin3:8b", "mistral:7b"]
ollama_port = 12345
kokoro_port = 4321
"""
        (tmp_path / ".ai-shell.toml").write_bytes(toml_content)
        config = load_config(project_dir=tmp_path)

        assert config.image == "custom/image"
        assert config.image_tag == "2.0.0"
        assert config.primary_chat_model == "llama3:8b"
        assert config.secondary_chat_model == "llama3:8b-uncensored"
        assert config.primary_coding_model == "qwen-coder:test"
        assert config.secondary_coding_model == "qwen-coder-uncensored:test"
        assert config.extra_models == ["dolphin3:8b", "mistral:7b"]
        assert config.ollama_port == 12345
        assert config.kokoro_port == 4321

    def test_env_var_overrides(self, tmp_path):
        env = {
            "AI_SHELL_IMAGE": "env/image",
            "AI_SHELL_OLLAMA_PORT": "9999",
            "AI_SHELL_KOKORO_PORT": "4321",
        }
        with patch.dict("os.environ", env):
            config = load_config(project_dir=tmp_path)

        assert config.image == "env/image"
        assert config.ollama_port == 9999
        assert config.kokoro_port == 4321

    def test_env_vars_override_toml(self, tmp_path):
        toml_content = b"""
[container]
image = "toml/image"
"""
        (tmp_path / ".ai-shell.toml").write_bytes(toml_content)

        with patch.dict("os.environ", {"AI_SHELL_IMAGE": "env/image"}):
            config = load_config(project_dir=tmp_path)

        # Env var wins over TOML
        assert config.image == "env/image"

    def test_global_config_loaded(self, tmp_path):
        global_dir = tmp_path / ".config" / "ai-shell"
        global_dir.mkdir(parents=True)
        (global_dir / "config.toml").write_bytes(
            b"""
[llm]
primary_chat_model = "global-model"
"""
        )

        with patch("ai_shell.config.Path.home", return_value=tmp_path):
            config = load_config(project_dir=tmp_path)

        assert config.primary_chat_model == "global-model"

    def test_home_yaml_config_loaded(self, tmp_path):
        (tmp_path / ".ai-shell.yaml").write_text("llm:\n  primary_chat_model: home-yaml-model\n")

        with patch("ai_shell.config.Path.home", return_value=tmp_path):
            config = load_config(project_dir=tmp_path / "project")

        assert config.primary_chat_model == "home-yaml-model"

    def test_home_yaml_takes_precedence_over_config_dir(self, tmp_path):
        (tmp_path / ".ai-shell.yaml").write_text("llm:\n  primary_chat_model: home-yaml-wins\n")
        global_dir = tmp_path / ".config" / "ai-shell"
        global_dir.mkdir(parents=True)
        (global_dir / "config.toml").write_bytes(
            b'[llm]\nprimary_chat_model = "config-dir-loses"\n'
        )

        with patch("ai_shell.config.Path.home", return_value=tmp_path):
            config = load_config(project_dir=tmp_path / "project")

        assert config.primary_chat_model == "home-yaml-wins"

    def test_project_toml_overrides_global(self, tmp_path):
        global_dir = tmp_path / ".config" / "ai-shell"
        global_dir.mkdir(parents=True)
        (global_dir / "config.toml").write_bytes(
            b"""
[llm]
primary_chat_model = "global-model"
"""
        )
        (tmp_path / ".ai-shell.toml").write_bytes(
            b"""
[llm]
primary_chat_model = "project-model"
"""
        )

        with patch("ai_shell.config.Path.home", return_value=tmp_path):
            config = load_config(project_dir=tmp_path)

        assert config.primary_chat_model == "project-model"

    def test_legacy_primary_model_key_errors(self, tmp_path):
        (tmp_path / ".ai-shell.toml").write_bytes(b'[llm]\nprimary_model = "old-tag"\n')
        with pytest.raises(ValueError, match="primary_model"):
            load_config(project_dir=tmp_path)

    def test_legacy_fallback_model_key_errors(self, tmp_path):
        (tmp_path / ".ai-shell.toml").write_bytes(b'[llm]\nfallback_model = "old-tag"\n')
        with pytest.raises(ValueError, match="fallback_model"):
            load_config(project_dir=tmp_path)

    def test_legacy_primary_model_env_var_errors(self, tmp_path):
        with patch.dict("os.environ", {"AI_SHELL_PRIMARY_MODEL": "old-tag"}):
            with pytest.raises(ValueError, match="AI_SHELL_PRIMARY_MODEL"):
                load_config(project_dir=tmp_path)

    def test_new_env_vars_apply(self, tmp_path):
        env = {
            "AI_SHELL_PRIMARY_CHAT_MODEL": "env-chat",
            "AI_SHELL_SECONDARY_CHAT_MODEL": "env-chat-2",
            "AI_SHELL_PRIMARY_CODING_MODEL": "env-code",
            "AI_SHELL_SECONDARY_CODING_MODEL": "env-code-2",
        }
        with patch.dict("os.environ", env):
            config = load_config(project_dir=tmp_path)
        assert config.primary_chat_model == "env-chat"
        assert config.secondary_chat_model == "env-chat-2"
        assert config.primary_coding_model == "env-code"
        assert config.secondary_coding_model == "env-code-2"

    def test_extra_env_accumulated(self, tmp_path):
        (tmp_path / ".ai-shell.toml").write_bytes(
            b"""
[container]
extra_env = { FOO = "bar", BAZ = "qux" }
"""
        )
        config = load_config(project_dir=tmp_path)
        assert config.extra_env == {"FOO": "bar", "BAZ": "qux"}

    def test_dev_ports_defaults(self):
        config = AiShellConfig()
        assert config.dev_ports == sorted(DEFAULT_DEV_PORTS)

    def test_dev_ports_with_extras(self):
        config = AiShellConfig(extra_ports=[9000, 9229])
        assert 9000 in config.dev_ports
        assert 9229 in config.dev_ports
        # Defaults still present
        assert 3000 in config.dev_ports

    def test_dev_ports_deduplicates(self):
        config = AiShellConfig(extra_ports=[3000, 8000, 9000])
        assert config.dev_ports == sorted(set(DEFAULT_DEV_PORTS + [9000]))

    def test_dev_ports_sorted(self):
        config = AiShellConfig(extra_ports=[100, 50000])
        ports = config.dev_ports
        assert ports == sorted(ports)

    def test_extra_ports_from_toml(self, tmp_path):
        toml_content = b"""
[container]
ports = [9000, 9229]
"""
        (tmp_path / ".ai-shell.toml").write_bytes(toml_content)
        config = load_config(project_dir=tmp_path)
        assert 9000 in config.dev_ports
        assert 9229 in config.dev_ports

    def test_extra_ports_from_env_var(self, tmp_path):
        with patch.dict("os.environ", {"AI_SHELL_PORTS": "9000,9229"}):
            config = load_config(project_dir=tmp_path)
        assert 9000 in config.dev_ports
        assert 9229 in config.dev_ports

    def test_invalid_toml_gracefully_ignored(self, tmp_path):
        (tmp_path / ".ai-shell.toml").write_text("this is not valid toml {{{")
        config = load_config(project_dir=tmp_path)
        # Should load defaults without error
        assert config.image == "svange/augint-shell"

    def test_yaml_config_loaded(self, tmp_path):
        yaml_content = "container:\n  image: yaml/image\n  image_tag: '3.0.0'\n"
        (tmp_path / ".ai-shell.yaml").write_text(yaml_content)
        config = load_config(project_dir=tmp_path)
        assert config.image == "yaml/image"
        assert config.image_tag == "3.0.0"

    def test_yaml_takes_precedence_over_toml(self, tmp_path):
        (tmp_path / ".ai-shell.yaml").write_text("container:\n  image: yaml/wins\n")
        (tmp_path / ".ai-shell.toml").write_bytes(b'[container]\nimage = "toml/loses"\n')
        config = load_config(project_dir=tmp_path)
        assert config.image == "yaml/wins"

    def test_toml_still_loads_when_no_yaml(self, tmp_path):
        (tmp_path / ".ai-shell.toml").write_bytes(b'[container]\nimage = "toml/fallback"\n')
        config = load_config(project_dir=tmp_path)
        assert config.image == "toml/fallback"

    def test_project_section_ignored(self, tmp_path):
        toml_content = b'[project]\nrepo_type = "library"\n'
        (tmp_path / ".ai-shell.toml").write_bytes(toml_content)
        config = load_config(project_dir=tmp_path)
        assert not hasattr(config, "repo_type")

    def test_legacy_toml_name_still_loaded(self, tmp_path):
        (tmp_path / "ai-shell.toml").write_bytes(b"""
[container]
image = "legacy/image"
""")
        config = load_config(project_dir=tmp_path)
        assert config.image == "legacy/image"

    def test_hidden_toml_takes_precedence(self, tmp_path):
        (tmp_path / "ai-shell.toml").write_bytes(b"""
[container]
image = "legacy/image"
""")
        (tmp_path / ".ai-shell.toml").write_bytes(b"""
[container]
image = "hidden/image"
""")
        config = load_config(project_dir=tmp_path)
        assert config.image == "hidden/image"


class TestImageTagConfig:
    def test_default_image_tag_is_latest(self):
        config = AiShellConfig()
        assert config.image_tag == "latest"
        assert config.full_image == "svange/augint-shell:latest"

    def test_pinned_image_uses_version_tag(self, tmp_path):
        from ai_shell import __version__

        (tmp_path / ".ai-shell.yaml").write_text("container:\n  pinned_image: true\n")
        config = load_config(project_dir=tmp_path)
        assert config.image_tag == __version__

    def test_pinned_image_does_not_override_explicit_tag(self, tmp_path):
        (tmp_path / ".ai-shell.yaml").write_text(
            "container:\n  pinned_image: true\n  image_tag: '0.50.0'\n"
        )
        config = load_config(project_dir=tmp_path)
        # Explicit image_tag wins over pinned_image
        assert config.image_tag == "0.50.0"

    def test_pinned_image_env_var(self, tmp_path):
        from ai_shell import __version__

        with patch.dict("os.environ", {"AI_SHELL_PINNED_IMAGE": "true"}):
            config = load_config(project_dir=tmp_path)
        assert config.image_tag == __version__

    def test_pinned_image_false_keeps_latest(self, tmp_path):
        (tmp_path / ".ai-shell.yaml").write_text("container:\n  pinned_image: false\n")
        config = load_config(project_dir=tmp_path)
        assert config.image_tag == "latest"


class TestWhisperConfig:
    def test_whisper_toml_overrides(self, tmp_path):
        (tmp_path / ".ai-shell.toml").write_bytes(
            b"""
[llm]
whisper_port = 9100
whisper_model = "Systran/faster-whisper-tiny"
"""
        )
        config = load_config(project_dir=tmp_path)
        assert config.whisper_port == 9100
        assert config.whisper_model == "Systran/faster-whisper-tiny"

    def test_whisper_yaml_overrides(self, tmp_path):
        (tmp_path / ".ai-shell.yaml").write_text(
            "llm:\n  whisper_port: 9200\n  whisper_model: Systran/faster-whisper-small\n"
        )
        config = load_config(project_dir=tmp_path)
        assert config.whisper_port == 9200
        assert config.whisper_model == "Systran/faster-whisper-small"

    def test_whisper_env_var_overrides(self, tmp_path):
        env = {
            "AI_SHELL_WHISPER_PORT": "9300",
            "AI_SHELL_WHISPER_MODEL": "Systran/faster-whisper-base",
        }
        with patch.dict("os.environ", env):
            config = load_config(project_dir=tmp_path)
        assert config.whisper_port == 9300
        assert config.whisper_model == "Systran/faster-whisper-base"

    def test_whisper_env_overrides_yaml(self, tmp_path):
        (tmp_path / ".ai-shell.yaml").write_text(
            "llm:\n  whisper_port: 9200\n  whisper_model: yaml-model\n"
        )
        env = {
            "AI_SHELL_WHISPER_PORT": "9400",
            "AI_SHELL_WHISPER_MODEL": "env-model",
        }
        with patch.dict("os.environ", env):
            config = load_config(project_dir=tmp_path)
        assert config.whisper_port == 9400
        assert config.whisper_model == "env-model"


class TestVoiceAgentConfig:
    def test_voice_agent_yaml_overrides(self, tmp_path):
        (tmp_path / ".ai-shell.yaml").write_text(
            "voice_agent:\n"
            "  port: 9010\n"
            "  profile: swap\n"
            "  vad:\n"
            "    silence_timeout_ms: 1500\n"
            "    barge_in: false\n"
            "  wake_word:\n"
            "    enabled: true\n"
            "    name: hey_gigachad\n"
        )
        config = load_config(project_dir=tmp_path)
        assert config.voice_agent.port == 9010
        assert config.voice_agent.profile == "swap"
        assert config.voice_agent.vad.silence_timeout_ms == 1500
        assert config.voice_agent.vad.barge_in is False
        assert config.voice_agent.wake_word.enabled is True
        assert config.voice_agent.wake_word.name == "hey_gigachad"

    def test_voice_agent_nested_profiles_merge(self, tmp_path):
        """Partial profile overrides must leave other profiles intact."""
        (tmp_path / ".ai-shell.yaml").write_text(
            "voice_agent:\n  profiles:\n    resident:\n      primary: my-model:latest\n"
        )
        config = load_config(project_dir=tmp_path)
        # Overridden.
        assert config.voice_agent.profiles["resident"].primary == "my-model:latest"
        # Untouched fields keep defaults.
        assert (
            config.voice_agent.profiles["resident"].secondary == "huihui_ai/qwen3.5-abliterated:14b"
        )
        assert config.voice_agent.profiles["swap"].primary == "qwen3.5:27b"

    def test_voice_agent_tools_partial_override(self, tmp_path):
        (tmp_path / ".ai-shell.yaml").write_text(
            "voice_agent:\n  tools:\n    filesystem:\n      enabled: true\n"
        )
        config = load_config(project_dir=tmp_path)
        assert config.voice_agent.tools.filesystem.enabled is True
        # Other tools keep defaults.
        assert config.voice_agent.tools.web_search.enabled is False
        assert config.voice_agent.tools.web_search.provider == "brave"
        assert config.voice_agent.tools.github.enabled is False

    def test_voice_agent_env_var_overrides(self, tmp_path):
        env = {
            "AI_SHELL_VOICE_AGENT_PORT": "9999",
            "AI_SHELL_VOICE_AGENT_DOMAIN": "voice.example.com",
            "AI_SHELL_VOICE_AGENT_PROFILE": "swap",
        }
        with patch.dict("os.environ", env):
            config = load_config(project_dir=tmp_path)
        assert config.voice_agent.port == 9999
        assert config.voice_agent.domain == "voice.example.com"
        assert config.voice_agent.profile == "swap"

    def test_voice_agent_env_overrides_yaml(self, tmp_path):
        (tmp_path / ".ai-shell.yaml").write_text("voice_agent:\n  port: 7000\n")
        env = {"AI_SHELL_VOICE_AGENT_PORT": "9000"}
        with patch.dict("os.environ", env):
            config = load_config(project_dir=tmp_path)
        assert config.voice_agent.port == 9000


class TestAwsConfig:
    def test_aws_defaults_empty(self, tmp_path):
        config = load_config(project_dir=tmp_path)
        assert config.ai_profile == ""
        assert config.aws_region == ""
        assert config.bedrock_profile == ""
        assert config.claude_provider == ""
        assert not hasattr(config, "opencode_provider")
        assert not hasattr(config, "codex_provider")
        assert not hasattr(config, "codex_openai_api_key")
        assert not hasattr(config, "codex_profile")
        assert not hasattr(config, "aider_model")

    def test_ai_profile_from_toml(self, tmp_path):
        (tmp_path / ".ai-shell.toml").write_bytes(b"""
[aws]
ai_profile = "my-infra"
""")
        config = load_config(project_dir=tmp_path)
        assert config.ai_profile == "my-infra"

    def test_bedrock_profile_from_toml(self, tmp_path):
        (tmp_path / ".ai-shell.toml").write_bytes(b"""
[aws]
bedrock_profile = "my-ai-account"
""")
        config = load_config(project_dir=tmp_path)
        assert config.bedrock_profile == "my-ai-account"

    def test_aws_region_from_toml(self, tmp_path):
        (tmp_path / ".ai-shell.toml").write_bytes(b"""
[aws]
region = "eu-west-1"
""")
        config = load_config(project_dir=tmp_path)
        assert config.aws_region == "eu-west-1"

    def test_claude_provider_from_toml(self, tmp_path):
        (tmp_path / ".ai-shell.toml").write_bytes(b"""
[claude]
provider = "aws"
""")
        config = load_config(project_dir=tmp_path)
        assert config.claude_provider == "aws"

    def test_full_aws_config(self, tmp_path):
        (tmp_path / ".ai-shell.toml").write_bytes(b"""
[aws]
ai_profile = "infra-acct"
bedrock_profile = "ai-acct"
region = "us-west-2"

[claude]
provider = "aws"
""")
        config = load_config(project_dir=tmp_path)
        assert config.ai_profile == "infra-acct"
        assert config.bedrock_profile == "ai-acct"
        assert config.aws_region == "us-west-2"
        assert config.claude_provider == "aws"

    def test_provider_env_vars(self, tmp_path):
        env = {"AI_SHELL_CLAUDE_PROVIDER": "aws"}
        with patch.dict("os.environ", env):
            config = load_config(project_dir=tmp_path)
        assert config.claude_provider == "aws"

    def test_bedrock_profile_env_var(self, tmp_path):
        with patch.dict("os.environ", {"AI_SHELL_BEDROCK_PROFILE": "ai-acct"}):
            config = load_config(project_dir=tmp_path)
        assert config.bedrock_profile == "ai-acct"

    def test_ai_profile_env_var(self, tmp_path):
        with patch.dict("os.environ", {"AI_SHELL_AI_PROFILE": "infra-acct"}):
            config = load_config(project_dir=tmp_path)
        assert config.ai_profile == "infra-acct"

    def test_openai_profile_from_yaml(self, tmp_path):
        (tmp_path / ".ai-shell.yaml").write_text("openai:\n  profile: personal\n")
        config = load_config(project_dir=tmp_path)
        assert config.openai_profile == "personal"

    def test_openai_profile_from_toml(self, tmp_path):
        (tmp_path / ".ai-shell.toml").write_bytes(b"""
[openai]
profile = "aillc"
""")
        config = load_config(project_dir=tmp_path)
        assert config.openai_profile == "aillc"

    def test_openai_profile_env_var(self, tmp_path):
        with patch.dict("os.environ", {"AI_SHELL_OPENAI_PROFILE": "woxom"}):
            config = load_config(project_dir=tmp_path)
        assert config.openai_profile == "woxom"

    def test_openai_profile_default_empty(self, tmp_path):
        config = load_config(project_dir=tmp_path)
        assert config.openai_profile == ""

    def test_env_overrides_toml(self, tmp_path):
        (tmp_path / ".ai-shell.toml").write_bytes(b"""
[claude]
provider = "anthropic"
""")
        with patch.dict("os.environ", {"AI_SHELL_CLAUDE_PROVIDER": "aws"}):
            config = load_config(project_dir=tmp_path)
        assert config.claude_provider == "aws"

    def test_tool_specific_sections_are_ignored(self, tmp_path):
        (tmp_path / ".ai-shell.toml").write_bytes(b"""
[aider]
model = "ollama_chat/ignored"

[opencode]
provider = "aws"

[codex]
provider = "aws"
openai_api_key = "sk-test-123"
profile = "bedrock-acct"
""")
        config = load_config(project_dir=tmp_path)
        assert not hasattr(config, "aider_model")
        assert not hasattr(config, "opencode_provider")
        assert not hasattr(config, "codex_provider")
        assert not hasattr(config, "codex_openai_api_key")
        assert not hasattr(config, "codex_profile")

    def test_tool_specific_env_vars_are_ignored(self, tmp_path):
        env = {
            "AI_SHELL_AIDER_MODEL": "ollama_chat/ignored",
            "AI_SHELL_OPENCODE_PROVIDER": "aws",
            "AI_SHELL_CODEX_PROVIDER": "aws",
            "AI_SHELL_CODEX_OPENAI_API_KEY": "sk-env-456",
            "AI_SHELL_CODEX_PROFILE": "env-profile",
        }
        with patch.dict("os.environ", env):
            config = load_config(project_dir=tmp_path)
        assert not hasattr(config, "aider_model")
        assert not hasattr(config, "opencode_provider")
        assert not hasattr(config, "codex_provider")
        assert not hasattr(config, "codex_openai_api_key")
        assert not hasattr(config, "codex_profile")
