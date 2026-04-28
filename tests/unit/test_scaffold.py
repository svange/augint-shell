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

    def test_generated_yaml_is_valid(self, tmp_path):
        scaffold_project(tmp_path)
        content = (tmp_path / ".ai-shell.yaml").read_text()
        parsed = yaml.safe_load(content)
        # llm section is live (4 slots + extras); other sections stay commented.
        assert parsed is not None
        assert "llm" in parsed
        for key in (
            "primary_chat_model",
            "secondary_chat_model",
            "primary_coding_model",
            "secondary_coding_model",
        ):
            assert key in parsed["llm"]
        assert "container" not in parsed
        assert "aws" not in parsed
        assert "claude" not in parsed


class TestScaffoldGlobal:
    def test_creates_env_example(self, tmp_path):
        with patch("ai_shell.scaffold.Path.home", return_value=tmp_path):
            scaffold_global()
        assert (tmp_path / ".augint" / ".env.example").is_file()

    def test_creates_ai_shell_example_yaml(self, tmp_path):
        with patch("ai_shell.scaffold.Path.home", return_value=tmp_path):
            scaffold_global()
        assert (tmp_path / ".augint" / ".ai-shell.example.yaml").is_file()

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
