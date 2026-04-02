"""Tests for ai_shell.config module."""

from unittest.mock import patch

from ai_shell.config import AiShellConfig, load_config


class TestAiShellConfig:
    def test_defaults(self):
        config = AiShellConfig()
        assert config.image == "svange/augint-shell"
        assert config.primary_model == "qwen3.5:27b"
        assert config.ollama_port == 11434
        assert config.webui_port == 3000

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
primary_model = "llama3:8b"
ollama_port = 12345

[aider]
model = "ollama_chat/llama3:8b"
"""
        (tmp_path / "ai-shell.toml").write_bytes(toml_content)
        config = load_config(project_dir=tmp_path)

        assert config.image == "custom/image"
        assert config.image_tag == "2.0.0"
        assert config.primary_model == "llama3:8b"
        assert config.ollama_port == 12345
        assert config.aider_model == "ollama_chat/llama3:8b"

    def test_env_var_overrides(self, tmp_path):
        env = {
            "AI_SHELL_IMAGE": "env/image",
            "AI_SHELL_OLLAMA_PORT": "9999",
        }
        with patch.dict("os.environ", env):
            config = load_config(project_dir=tmp_path)

        assert config.image == "env/image"
        assert config.ollama_port == 9999

    def test_env_vars_override_toml(self, tmp_path):
        toml_content = b"""
[container]
image = "toml/image"
"""
        (tmp_path / "ai-shell.toml").write_bytes(toml_content)

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
primary_model = "global-model"
"""
        )

        with patch("ai_shell.config.Path.home", return_value=tmp_path):
            config = load_config(project_dir=tmp_path)

        assert config.primary_model == "global-model"

    def test_project_toml_overrides_global(self, tmp_path):
        global_dir = tmp_path / ".config" / "ai-shell"
        global_dir.mkdir(parents=True)
        (global_dir / "config.toml").write_bytes(
            b"""
[llm]
primary_model = "global-model"
"""
        )
        (tmp_path / "ai-shell.toml").write_bytes(
            b"""
[llm]
primary_model = "project-model"
"""
        )

        with patch("ai_shell.config.Path.home", return_value=tmp_path):
            config = load_config(project_dir=tmp_path)

        assert config.primary_model == "project-model"

    def test_extra_env_accumulated(self, tmp_path):
        (tmp_path / "ai-shell.toml").write_bytes(
            b"""
[container]
extra_env = { FOO = "bar", BAZ = "qux" }
"""
        )
        config = load_config(project_dir=tmp_path)
        assert config.extra_env == {"FOO": "bar", "BAZ": "qux"}

    def test_invalid_toml_gracefully_ignored(self, tmp_path):
        (tmp_path / "ai-shell.toml").write_text("this is not valid toml {{{")
        config = load_config(project_dir=tmp_path)
        # Should load defaults without error
        assert config.image == "svange/augint-shell"
