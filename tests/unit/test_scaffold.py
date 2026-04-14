"""Tests for ai_shell.scaffold module."""

import yaml

from ai_shell.scaffold import scaffold_project


class TestScaffoldProject:
    def test_creates_yaml(self, tmp_path):
        scaffold_project(tmp_path)
        assert (tmp_path / ".ai-shell.yaml").is_file()

    def test_yaml_has_commented_sections(self, tmp_path):
        scaffold_project(tmp_path)
        content = (tmp_path / ".ai-shell.yaml").read_text()
        assert "# container:" in content or "container:" in content
        assert "# llm:" in content or "llm:" in content
        assert "# aider:" in content or "aider:" in content

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
        # All content is commented out, so parsed should be None
        assert parsed is None
