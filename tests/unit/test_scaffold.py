"""Tests for ai_shell.scaffold module."""

import json

import yaml

from ai_shell.scaffold import (
    AGENTS_SKILL_DIRS,
    CLAUDE_SKILL_DIRS,
    scaffold_aider,
    scaffold_claude,
    scaffold_codex,
    scaffold_opencode,
    scaffold_project,
)


class TestScaffoldClaude:
    def test_creates_settings_json(self, tmp_path):
        scaffold_claude(tmp_path)
        assert (tmp_path / ".claude" / "settings.json").is_file()

    def test_creates_all_skill_dirs(self, tmp_path):
        scaffold_claude(tmp_path)
        skills_dir = tmp_path / ".claude" / "skills"
        for skill_name in CLAUDE_SKILL_DIRS:
            assert (skills_dir / skill_name / "SKILL.md").is_file(), f"Missing skill: {skill_name}"

    def test_skill_count_matches(self, tmp_path):
        scaffold_claude(tmp_path)
        skills_dir = tmp_path / ".claude" / "skills"
        actual = sorted(d.name for d in skills_dir.iterdir() if d.is_dir())
        assert actual == sorted(CLAUDE_SKILL_DIRS)

    def test_skill_files_have_frontmatter(self, tmp_path):
        scaffold_claude(tmp_path)
        skills_dir = tmp_path / ".claude" / "skills"
        for skill_name in CLAUDE_SKILL_DIRS:
            content = (skills_dir / skill_name / "SKILL.md").read_text()
            assert content.startswith("---"), f"{skill_name}/SKILL.md missing YAML frontmatter"
            # Verify frontmatter closes
            second_marker = content.index("---", 3)
            frontmatter = content[3:second_marker]
            assert "name:" in frontmatter, f"{skill_name}/SKILL.md missing 'name' in frontmatter"
            assert "description:" in frontmatter, (
                f"{skill_name}/SKILL.md missing 'description' in frontmatter"
            )

    def test_settings_json_is_valid(self, tmp_path):
        scaffold_claude(tmp_path)
        content = (tmp_path / ".claude" / "settings.json").read_text()
        data = json.loads(content)
        assert "env" in data
        assert "permissions" in data
        assert "allow" in data["permissions"]
        assert "deny" in data["permissions"]

    def test_init_skips_existing_files(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.json"
        settings.write_text("original")

        scaffold_claude(tmp_path, overwrite=False)
        assert settings.read_text() == "original"

    def test_update_overwrites_existing_files(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.json"
        settings.write_text("original")

        scaffold_claude(tmp_path, overwrite=True)
        assert settings.read_text() != "original"
        data = json.loads(settings.read_text())
        assert "env" in data

    def test_settings_excludes_user_specific_fields(self, tmp_path):
        scaffold_claude(tmp_path)
        data = json.loads((tmp_path / ".claude" / "settings.json").read_text())
        assert "statusLine" not in data
        assert "feedbackSurveyState" not in data
        assert "effortLevel" not in data

    def test_settings_has_workflow_permissions(self, tmp_path):
        scaffold_claude(tmp_path)
        data = json.loads((tmp_path / ".claude" / "settings.json").read_text())
        allow = data["permissions"]["allow"]
        # Verify new permissions needed by workflow skills
        assert "Bash(gh pr create:*)" in allow
        assert "Bash(gh pr merge:*)" in allow
        assert "Bash(gh run list:*)" in allow
        assert "Bash(gh run view:*)" in allow
        assert "Bash(gh run watch:*)" in allow
        assert "Bash(uv run pre-commit:*)" in allow


class TestScaffoldProject:
    def test_creates_toml_only(self, tmp_path):
        scaffold_project(tmp_path)
        assert (tmp_path / "ai-shell.toml").is_file()
        # opencode.json is no longer created by scaffold_project
        assert not (tmp_path / "opencode.json").exists()

    def test_toml_has_commented_sections(self, tmp_path):
        scaffold_project(tmp_path)
        content = (tmp_path / "ai-shell.toml").read_text()
        assert "# [container]" in content
        assert "# [llm]" in content
        assert "# [aider]" in content

    def test_init_skips_existing(self, tmp_path):
        (tmp_path / "ai-shell.toml").write_text("original")
        scaffold_project(tmp_path, overwrite=False)
        assert (tmp_path / "ai-shell.toml").read_text() == "original"

    def test_update_overwrites_existing(self, tmp_path):
        (tmp_path / "ai-shell.toml").write_text("original")
        scaffold_project(tmp_path, overwrite=True)
        assert (tmp_path / "ai-shell.toml").read_text() != "original"


class TestScaffoldOpencode:
    def test_creates_opencode_json(self, tmp_path):
        scaffold_opencode(tmp_path)
        assert (tmp_path / "opencode.json").is_file()

    def test_opencode_json_is_valid(self, tmp_path):
        scaffold_opencode(tmp_path)
        data = json.loads((tmp_path / "opencode.json").read_text())
        assert data["$schema"] == "https://opencode.ai/config.json"
        assert data["model"] == "ollama/qwen3.5:27b"
        assert "host.docker.internal:11434" in data["provider"]["ollama"]["options"]["baseURL"]

    def test_opencode_json_has_permissions(self, tmp_path):
        scaffold_opencode(tmp_path)
        data = json.loads((tmp_path / "opencode.json").read_text())
        perm = data["permission"]
        assert perm["bash"] == "allow"
        assert perm["read"] == "allow"
        assert perm["external_directory"] == "ask"
        assert perm["doom_loop"] == "ask"

    def test_opencode_json_has_both_models(self, tmp_path):
        scaffold_opencode(tmp_path)
        data = json.loads((tmp_path / "opencode.json").read_text())
        models = data["provider"]["ollama"]["models"]
        assert "qwen3.5:27b" in models
        assert "qwen3-coder-next" in models

    def test_opencode_json_has_bedrock_provider(self, tmp_path):
        scaffold_opencode(tmp_path)
        data = json.loads((tmp_path / "opencode.json").read_text())
        bedrock = data["provider"]["amazon-bedrock"]
        assert bedrock["options"]["region"] == "{env:AWS_REGION}"
        assert bedrock["options"]["profile"] == "{env:AWS_PROFILE}"

    def test_opencode_json_has_instructions(self, tmp_path):
        scaffold_opencode(tmp_path)
        data = json.loads((tmp_path / "opencode.json").read_text())
        assert "AGENTS.md" in data["instructions"]

    def test_creates_agents_md(self, tmp_path):
        scaffold_opencode(tmp_path)
        assert (tmp_path / "AGENTS.md").is_file()

    def test_creates_agents_skills(self, tmp_path):
        scaffold_opencode(tmp_path)
        skills_dir = tmp_path / ".agents" / "skills"
        for skill_name in AGENTS_SKILL_DIRS:
            assert (skills_dir / skill_name / "SKILL.md").is_file(), (
                f"Missing agent skill: {skill_name}"
            )

    def test_init_skips_existing(self, tmp_path):
        (tmp_path / "opencode.json").write_text("original")
        scaffold_opencode(tmp_path, overwrite=False)
        assert (tmp_path / "opencode.json").read_text() == "original"

    def test_update_overwrites_existing(self, tmp_path):
        (tmp_path / "opencode.json").write_text("original")
        scaffold_opencode(tmp_path, overwrite=True)
        assert (tmp_path / "opencode.json").read_text() != "original"


class TestScaffoldCodex:
    def test_creates_config_toml(self, tmp_path):
        scaffold_codex(tmp_path)
        assert (tmp_path / ".codex" / "config.toml").is_file()

    def test_config_toml_has_permissions(self, tmp_path):
        scaffold_codex(tmp_path)
        content = (tmp_path / ".codex" / "config.toml").read_text()
        assert "[permissions.default]" in content
        assert "[permissions.default.filesystem]" in content

    def test_config_toml_has_model(self, tmp_path):
        scaffold_codex(tmp_path)
        content = (tmp_path / ".codex" / "config.toml").read_text()
        assert 'model = "o4-mini"' in content

    def test_creates_agents_md(self, tmp_path):
        scaffold_codex(tmp_path)
        assert (tmp_path / "AGENTS.md").is_file()

    def test_creates_agents_skills(self, tmp_path):
        scaffold_codex(tmp_path)
        skills_dir = tmp_path / ".agents" / "skills"
        for skill_name in AGENTS_SKILL_DIRS:
            assert (skills_dir / skill_name / "SKILL.md").is_file(), (
                f"Missing agent skill: {skill_name}"
            )

    def test_skill_files_have_frontmatter(self, tmp_path):
        scaffold_codex(tmp_path)
        skills_dir = tmp_path / ".agents" / "skills"
        for skill_name in AGENTS_SKILL_DIRS:
            content = (skills_dir / skill_name / "SKILL.md").read_text()
            assert content.startswith("---"), f"{skill_name}/SKILL.md missing YAML frontmatter"
            second_marker = content.index("---", 3)
            frontmatter = content[3:second_marker]
            assert "name:" in frontmatter, f"{skill_name}/SKILL.md missing 'name'"
            assert "description:" in frontmatter, f"{skill_name}/SKILL.md missing 'description'"

    def test_init_skips_existing(self, tmp_path):
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        config = codex_dir / "config.toml"
        config.write_text("original")
        scaffold_codex(tmp_path, overwrite=False)
        assert config.read_text() == "original"

    def test_update_overwrites_existing(self, tmp_path):
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        config = codex_dir / "config.toml"
        config.write_text("original")
        scaffold_codex(tmp_path, overwrite=True)
        assert config.read_text() != "original"


class TestScaffoldAider:
    def test_creates_aider_conf(self, tmp_path):
        scaffold_aider(tmp_path)
        assert (tmp_path / ".aider.conf.yml").is_file()

    def test_aider_conf_is_valid_yaml(self, tmp_path):
        scaffold_aider(tmp_path)
        content = (tmp_path / ".aider.conf.yml").read_text()
        data = yaml.safe_load(content)
        assert isinstance(data, dict)

    def test_aider_conf_has_model(self, tmp_path):
        scaffold_aider(tmp_path)
        content = (tmp_path / ".aider.conf.yml").read_text()
        data = yaml.safe_load(content)
        assert data["model"] == "ollama_chat/qwen3.5:27b"

    def test_aider_conf_has_conventions_read(self, tmp_path):
        scaffold_aider(tmp_path)
        content = (tmp_path / ".aider.conf.yml").read_text()
        data = yaml.safe_load(content)
        assert "CONVENTIONS.md" in data["read"]

    def test_creates_conventions(self, tmp_path):
        scaffold_aider(tmp_path)
        assert (tmp_path / "CONVENTIONS.md").is_file()
        content = (tmp_path / "CONVENTIONS.md").read_text()
        assert "Conventions" in content

    def test_creates_aiderignore(self, tmp_path):
        scaffold_aider(tmp_path)
        assert (tmp_path / ".aiderignore").is_file()

    def test_aiderignore_has_env(self, tmp_path):
        scaffold_aider(tmp_path)
        content = (tmp_path / ".aiderignore").read_text()
        assert ".env" in content

    def test_init_skips_existing(self, tmp_path):
        (tmp_path / ".aider.conf.yml").write_text("original")
        scaffold_aider(tmp_path, overwrite=False)
        assert (tmp_path / ".aider.conf.yml").read_text() == "original"

    def test_update_overwrites_existing(self, tmp_path):
        (tmp_path / ".aider.conf.yml").write_text("original")
        scaffold_aider(tmp_path, overwrite=True)
        assert (tmp_path / ".aider.conf.yml").read_text() != "original"
