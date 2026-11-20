"""Tests for ai_shell.scaffold module."""

from unittest.mock import patch

import yaml

from ai_shell.scaffold import scaffold_global, scaffold_project


class TestScaffoldProject:
    def test_creates_yaml(self, tmp_path):
        scaffold_project(tmp_path)
        assert (tmp_path / ".ai-shell.yaml").is_file()

    def test_yaml_has_commented_sections(self, tmp_path):
        scaffold_project(tmp_path)
        content = (tmp_path / ".ai-shell.yaml").read_text()
        assert "# container:" in content or "container:" in content
        assert "# llm:" in content or "llm:" in content
        # The llm section documents the 4 role-specific slots.
        assert "primary_chat_model" in content
        assert "secondary_chat_model" in content
        assert "primary_coding_model" in content
        assert "secondary_coding_model" in content
        assert "extra_models" in content
        assert "aider" not in content.lower()

    def test_skips_existing(self, tmp_path):
        (tmp_path / ".ai-shell.yaml").write_text("original")
        scaffold_project(tmp_path)
        assert (tmp_path / ".ai-shell.yaml").read_text() == "original"


class TestProjectYamlOutput:
    def test_scaffold_generates_yaml(self, tmp_path):
        scaffold_project(tmp_path)
        assert (tmp_path / ".ai-shell.yaml").exists()
        assert not (tmp_path / ".ai-shell.toml").exists()

    def test_generated_yaml_has_no_project_key(self, tmp_path):
        scaffold_project(tmp_path)
        content = (tmp_path / ".ai-shell.yaml").read_text()
        assert "project:" not in content
        assert "repo_type" not in content

    def test_generated_yaml_sets_nothing(self, tmp_path):
        """A new project file must not override the global file until a line is uncommented."""
        scaffold_project(tmp_path)
        content = (tmp_path / ".ai-shell.yaml").read_text()
        assert yaml.safe_load(content) is None

    def test_every_example_key_is_read(self, tmp_path):
        """Regression: the old global example documented ``extra_ports``, which nothing read."""
        from ai_shell.config import load_config

        scaffold_project(tmp_path)
        lines = (tmp_path / ".ai-shell.yaml").read_text().splitlines()
        uncommented = "\n".join(
            line[2:] if line.startswith("# ") else line
            for line in lines
            if not line.startswith("##")
        )
        (tmp_path / ".ai-shell.yaml").write_text(uncommented)
        parsed = yaml.safe_load(uncommented)
        assert set(parsed) == {
            "opencode",
            "claude",
            "aws",
            "openai",
            "container",
            "llm",
            "expo",
            "vpn",
            "voice_agent",
        }

        config = load_config(project_dir=tmp_path)
        assert config.opencode_model == "openai.gpt-5.6-terra"
        assert config.opencode_subagent_model == "openai.gpt-5.6-luna"
        assert config.opencode_plugins == parsed["opencode"]["plugins"]
        assert config.opencode_instructions == parsed["opencode"]["instructions"]
        assert config.opencode_endpoints[0].name == "vllm"
        assert config.claude_account == "work"
        assert config.bedrock_model == parsed["aws"]["bedrock_model"]
        assert config.openai_profile == "work"
        assert {9000, 9229} <= set(config.extra_ports)
        assert config.node_modules_paths == ["apps/*"]
        assert config.image_pull_cache_ttl == 900
        assert config.image_pull_mode == "background"
        assert config.background_updates is True
        assert config.comfyui_port == 8188
        assert config.vpn_country == "United States"
        assert config.voice_agent.port == 8010

    def test_reference_matches_defaults(self):
        """The example plugins and instructions are the real defaults."""
        from ai_shell.opencode import DEFAULT_OPENCODE_INSTRUCTIONS, DEFAULT_OPENCODE_PLUGINS
        from ai_shell.scaffold import _read_template

        content = _read_template("ai-shell.yaml")
        for item in (*DEFAULT_OPENCODE_PLUGINS, *DEFAULT_OPENCODE_INSTRUCTIONS):
            assert item in content


class TestScaffoldGlobal:
    def test_creates_env_example(self, tmp_path):
        with patch("ai_shell.scaffold.Path.home", return_value=tmp_path):
            scaffold_global()
        assert (tmp_path / ".augint" / ".env.example").is_file()

    def test_creates_ai_shell_example_yaml(self, tmp_path):
        with patch("ai_shell.scaffold.Path.home", return_value=tmp_path):
            scaffold_global()
        example = tmp_path / ".augint" / ".ai-shell.example.yaml"
        assert example.is_file()
        assert "opencode:" in example.read_text()
        assert not (tmp_path / ".augint" / ".ai-shell.yaml").exists()

    def test_env_example_documents_shared_vars(self, tmp_path):
        with patch("ai_shell.scaffold.Path.home", return_value=tmp_path):
            scaffold_global()
        content = (tmp_path / ".augint" / ".env.example").read_text()
        assert "PRIMARY_CHAT_MODEL" in content
        assert "AWS_BEDROCK_PROFILE" in content
        assert "GH_TOKEN" in content
        assert "OLLAMA_PORT" in content

    def test_overwrites_existing_examples(self, tmp_path):
        augint_dir = tmp_path / ".augint"
        augint_dir.mkdir()
        (augint_dir / ".env.example").write_text("old content")
        with patch("ai_shell.scaffold.Path.home", return_value=tmp_path):
            scaffold_global()
        assert (augint_dir / ".env.example").read_text() != "old content"
