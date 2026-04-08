"""Tests for ai_shell.scaffold module."""

import json

import yaml

from ai_shell.scaffold import (
    AGENTS_SKILL_DIRS,
    CLAUDE_SKILL_DIRS,
    BranchStrategy,
    RepoType,
    _deep_merge_settings,
    scaffold_aider,
    scaffold_claude,
    scaffold_codex,
    scaffold_opencode,
    scaffold_project,
    skills_for_config,
)


class TestDeepMergeSettings:
    def test_adds_missing_keys_from_template(self):
        existing = {"a": 1}
        template = {"a": 1, "b": 2}
        result = _deep_merge_settings(existing, template)
        assert result == {"a": 1, "b": 2}

    def test_preserves_existing_scalar_values(self):
        existing = {"a": "user_value"}
        template = {"a": "template_value"}
        result = _deep_merge_settings(existing, template)
        assert result["a"] == "user_value"

    def test_recursively_merges_dicts(self):
        existing = {"env": {"USER_VAR": "1"}}
        template = {"env": {"USER_VAR": "2", "TEMPLATE_VAR": "3"}}
        result = _deep_merge_settings(existing, template)
        assert result["env"]["USER_VAR"] == "1"
        assert result["env"]["TEMPLATE_VAR"] == "3"

    def test_list_union_preserves_order(self):
        existing = {"allow": ["user_perm", "shared_perm"]}
        template = {"allow": ["shared_perm", "template_perm"]}
        result = _deep_merge_settings(existing, template)
        assert result["allow"] == ["user_perm", "shared_perm", "template_perm"]

    def test_list_union_no_duplicates(self):
        existing = {"items": ["a", "b", "c"]}
        template = {"items": ["b", "c", "d"]}
        result = _deep_merge_settings(existing, template)
        assert result["items"] == ["a", "b", "c", "d"]

    def test_empty_existing(self):
        result = _deep_merge_settings({}, {"a": 1, "b": [1, 2]})
        assert result == {"a": 1, "b": [1, 2]}

    def test_empty_template(self):
        result = _deep_merge_settings({"a": 1}, {})
        assert result == {"a": 1}

    def test_nested_permissions_merge(self):
        existing = {
            "permissions": {
                "allow": ["Bash(git status:*)"],
                "deny": ["Bash(rm -rf /*)"],
            }
        }
        template = {
            "permissions": {
                "allow": ["Bash(git status:*)", "Bash(git diff:*)"],
                "deny": ["Bash(rm -rf /*)", "Bash(terraform destroy:*)"],
            }
        }
        result = _deep_merge_settings(existing, template)
        assert result["permissions"]["allow"] == [
            "Bash(git status:*)",
            "Bash(git diff:*)",
        ]
        assert result["permissions"]["deny"] == [
            "Bash(rm -rf /*)",
            "Bash(terraform destroy:*)",
        ]


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

    def test_reset_overwrites_existing_files(self, tmp_path):
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

    def test_clean_removes_and_recreates(self, tmp_path):
        scaffold_claude(tmp_path)
        (tmp_path / ".claude" / "settings.local.json").write_text("{}")
        scaffold_claude(tmp_path, clean=True)
        assert (tmp_path / ".claude" / "settings.json").is_file()
        assert not (tmp_path / ".claude" / "settings.local.json").exists()

    def test_clean_works_on_empty_dir(self, tmp_path):
        scaffold_claude(tmp_path, clean=True)
        assert (tmp_path / ".claude" / "settings.json").is_file()
        for skill_name in CLAUDE_SKILL_DIRS:
            assert (tmp_path / ".claude" / "skills" / skill_name / "SKILL.md").is_file()

    def test_does_not_create_notes_md(self, tmp_path):
        scaffold_claude(tmp_path)
        assert not (tmp_path / "INSTITUTIONAL_KNOWLEDGE.md").exists()

    # -- merge (--update) tests --

    def test_update_merges_settings_preserves_user_allow(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "env": {},
                    "permissions": {
                        "allow": ["Bash(my-custom-tool:*)"],
                        "deny": [],
                    },
                }
            )
        )

        scaffold_claude(tmp_path, merge=True)
        data = json.loads(settings.read_text())
        assert "Bash(my-custom-tool:*)" in data["permissions"]["allow"]
        assert "Bash(git status:*)" in data["permissions"]["allow"]

    def test_update_merges_settings_preserves_user_env(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "env": {"MY_CUSTOM_VAR": "hello"},
                    "permissions": {"allow": [], "deny": []},
                }
            )
        )

        scaffold_claude(tmp_path, merge=True)
        data = json.loads(settings.read_text())
        assert data["env"]["MY_CUSTOM_VAR"] == "hello"
        assert data["env"]["PYTHONDONTWRITEBYTECODE"] == "1"

    def test_update_merges_settings_preserves_user_deny(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "env": {},
                    "permissions": {
                        "allow": [],
                        "deny": ["Bash(my-dangerous-cmd:*)"],
                    },
                }
            )
        )

        scaffold_claude(tmp_path, merge=True)
        data = json.loads(settings.read_text())
        assert "Bash(my-dangerous-cmd:*)" in data["permissions"]["deny"]
        assert "Bash(rm -rf /*)" in data["permissions"]["deny"]

    def test_update_merges_settings_preserves_user_scalars(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "env": {},
                    "permissions": {"allow": [], "deny": []},
                    "enableAllProjectMcpServers": True,
                }
            )
        )

        scaffold_claude(tmp_path, merge=True)
        data = json.loads(settings.read_text())
        assert data["enableAllProjectMcpServers"] is True

    def test_update_creates_settings_if_missing(self, tmp_path):
        scaffold_claude(tmp_path, merge=True)
        assert (tmp_path / ".claude" / "settings.json").is_file()
        data = json.loads((tmp_path / ".claude" / "settings.json").read_text())
        assert "permissions" in data

    def test_update_overwrites_managed_skills(self, tmp_path):
        scaffold_claude(tmp_path)
        skill_path = tmp_path / ".claude" / "skills" / "ai-pick-issue" / "SKILL.md"
        skill_path.write_text("modified content")

        scaffold_claude(tmp_path, merge=True)
        assert skill_path.read_text() != "modified content"
        assert skill_path.read_text().startswith("---")

    def test_update_preserves_user_skills(self, tmp_path):
        scaffold_claude(tmp_path)
        custom_skill = tmp_path / ".claude" / "skills" / "my-custom-skill" / "SKILL.md"
        custom_skill.parent.mkdir(parents=True)
        custom_skill.write_text("my custom skill content")

        scaffold_claude(tmp_path, merge=True)
        assert custom_skill.read_text() == "my custom skill content"


class TestScaffoldProject:
    def test_creates_toml_only(self, tmp_path):
        scaffold_project(tmp_path)
        assert (tmp_path / ".ai-shell.toml").is_file()
        # opencode.json is no longer created by scaffold_project
        assert not (tmp_path / "opencode.json").exists()

    def test_toml_has_commented_sections(self, tmp_path):
        scaffold_project(tmp_path)
        content = (tmp_path / ".ai-shell.toml").read_text()
        assert "# [container]" in content
        assert "# [llm]" in content
        assert "# [aider]" in content

    def test_init_skips_existing(self, tmp_path):
        (tmp_path / ".ai-shell.toml").write_text("original")
        scaffold_project(tmp_path, overwrite=False)
        assert (tmp_path / ".ai-shell.toml").read_text() == "original"

    def test_reset_overwrites_existing(self, tmp_path):
        (tmp_path / ".ai-shell.toml").write_text("original")
        scaffold_project(tmp_path, overwrite=True)
        assert (tmp_path / ".ai-shell.toml").read_text() != "original"

    def test_update_overwrites_toml(self, tmp_path):
        (tmp_path / ".ai-shell.toml").write_text("original")
        scaffold_project(tmp_path, merge=True)
        assert (tmp_path / ".ai-shell.toml").read_text() != "original"

    def test_clean_removes_and_recreates(self, tmp_path):
        scaffold_project(tmp_path)
        scaffold_project(tmp_path, clean=True)
        assert (tmp_path / ".ai-shell.toml").is_file()

    def test_clean_works_on_empty_dir(self, tmp_path):
        scaffold_project(tmp_path, clean=True)
        assert (tmp_path / ".ai-shell.toml").is_file()


class TestScaffoldOpencode:
    def test_creates_opencode_json(self, tmp_path):
        scaffold_opencode(tmp_path)
        assert (tmp_path / "opencode.json").is_file()

    def test_opencode_json_is_valid(self, tmp_path):
        scaffold_opencode(tmp_path)
        data = json.loads((tmp_path / "opencode.json").read_text())
        assert data["$schema"] == "https://opencode.ai/config.json"
        assert data["model"] == "ollama/qwen3-coder-next"
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

    def test_opencode_json_has_bedrock_models(self, tmp_path):
        scaffold_opencode(tmp_path)
        data = json.loads((tmp_path / "opencode.json").read_text())
        models = data["provider"]["amazon-bedrock"]["models"]
        assert "anthropic.claude-sonnet-4-20250514-v1:0" in models
        assert "anthropic.claude-opus-4-20250514-v1:0" in models
        assert "anthropic.claude-haiku-4-5-20251001-v1:0" in models

    def test_opencode_json_has_instructions(self, tmp_path):
        scaffold_opencode(tmp_path)
        data = json.loads((tmp_path / "opencode.json").read_text())
        assert "INSTITUTIONAL_KNOWLEDGE.md" in data["instructions"]

    def test_creates_notes_md(self, tmp_path):
        scaffold_opencode(tmp_path)
        assert (tmp_path / "INSTITUTIONAL_KNOWLEDGE.md").is_file()

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

    def test_reset_overwrites_existing(self, tmp_path):
        (tmp_path / "opencode.json").write_text("original")
        scaffold_opencode(tmp_path, overwrite=True)
        assert (tmp_path / "opencode.json").read_text() != "original"

    def test_update_merges_opencode_json(self, tmp_path):
        scaffold_opencode(tmp_path)
        data = json.loads((tmp_path / "opencode.json").read_text())
        data["permission"]["my_custom"] = "allow"
        (tmp_path / "opencode.json").write_text(json.dumps(data, indent=2))

        scaffold_opencode(tmp_path, merge=True)
        merged = json.loads((tmp_path / "opencode.json").read_text())
        assert merged["permission"]["my_custom"] == "allow"
        assert merged["permission"]["bash"] == "allow"

    def test_clean_removes_and_recreates(self, tmp_path):
        scaffold_opencode(tmp_path)
        (tmp_path / ".agents" / "unmanaged.txt").write_text("stale")
        scaffold_opencode(tmp_path, clean=True)
        assert (tmp_path / "opencode.json").is_file()
        assert (tmp_path / "INSTITUTIONAL_KNOWLEDGE.md").is_file()
        assert not (tmp_path / ".agents" / "unmanaged.txt").exists()

    def test_clean_works_on_empty_dir(self, tmp_path):
        scaffold_opencode(tmp_path, clean=True)
        assert (tmp_path / "opencode.json").is_file()


class TestScaffoldCodex:
    def test_creates_config_toml(self, tmp_path):
        scaffold_codex(tmp_path)
        assert (tmp_path / ".codex" / "config.toml").is_file()

    def test_config_toml_is_commented_reference(self, tmp_path):
        scaffold_codex(tmp_path)
        content = (tmp_path / ".codex" / "config.toml").read_text()
        assert "config-reference" in content
        # All settings should be commented out (no active values)
        for line in content.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                raise AssertionError(
                    f"Expected all-comments template, found active line: {stripped}"
                )

    def test_creates_notes_md(self, tmp_path):
        scaffold_codex(tmp_path)
        assert (tmp_path / "INSTITUTIONAL_KNOWLEDGE.md").is_file()

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

    def test_reset_overwrites_existing(self, tmp_path):
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        config = codex_dir / "config.toml"
        config.write_text("original")
        scaffold_codex(tmp_path, overwrite=True)
        assert config.read_text() != "original"

    def test_update_overwrites_config_toml(self, tmp_path):
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        config = codex_dir / "config.toml"
        config.write_text("original")
        scaffold_codex(tmp_path, merge=True)
        assert config.read_text() != "original"

    def test_clean_removes_and_recreates(self, tmp_path):
        scaffold_codex(tmp_path)
        (tmp_path / ".codex" / "unmanaged.txt").write_text("stale")
        scaffold_codex(tmp_path, clean=True)
        assert (tmp_path / ".codex" / "config.toml").is_file()
        assert not (tmp_path / ".codex" / "unmanaged.txt").exists()

    def test_clean_works_on_empty_dir(self, tmp_path):
        scaffold_codex(tmp_path, clean=True)
        assert (tmp_path / ".codex" / "config.toml").is_file()


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
        assert data["model"] == "ollama_chat/qwen3-coder-next"

    def test_aider_conf_has_notes_read(self, tmp_path):
        scaffold_aider(tmp_path)
        content = (tmp_path / ".aider.conf.yml").read_text()
        data = yaml.safe_load(content)
        assert "INSTITUTIONAL_KNOWLEDGE.md" in data["read"]

    def test_creates_notes_md(self, tmp_path):
        scaffold_aider(tmp_path)
        assert (tmp_path / "INSTITUTIONAL_KNOWLEDGE.md").is_file()
        content = (tmp_path / "INSTITUTIONAL_KNOWLEDGE.md").read_text()
        assert "# Institutional Notes" in content

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

    def test_reset_overwrites_existing(self, tmp_path):
        (tmp_path / ".aider.conf.yml").write_text("original")
        scaffold_aider(tmp_path, overwrite=True)
        assert (tmp_path / ".aider.conf.yml").read_text() != "original"

    def test_update_overwrites_existing(self, tmp_path):
        (tmp_path / ".aider.conf.yml").write_text("original")
        scaffold_aider(tmp_path, merge=True)
        assert (tmp_path / ".aider.conf.yml").read_text() != "original"

    def test_clean_removes_and_recreates(self, tmp_path):
        scaffold_aider(tmp_path)
        scaffold_aider(tmp_path, clean=True)
        assert (tmp_path / ".aider.conf.yml").is_file()
        assert (tmp_path / "INSTITUTIONAL_KNOWLEDGE.md").is_file()
        assert (tmp_path / ".aiderignore").is_file()

    def test_clean_works_on_empty_dir(self, tmp_path):
        scaffold_aider(tmp_path, clean=True)
        assert (tmp_path / ".aider.conf.yml").is_file()


class TestNotesFile:
    def test_notes_never_overwritten_by_reset(self, tmp_path):
        scaffold_codex(tmp_path)
        notes = tmp_path / "INSTITUTIONAL_KNOWLEDGE.md"
        notes.write_text("My custom notes")
        scaffold_codex(tmp_path, overwrite=True)
        assert notes.read_text() == "My custom notes"

    def test_notes_never_overwritten_by_update(self, tmp_path):
        scaffold_codex(tmp_path)
        notes = tmp_path / "INSTITUTIONAL_KNOWLEDGE.md"
        notes.write_text("My custom notes")
        scaffold_codex(tmp_path, merge=True)
        assert notes.read_text() == "My custom notes"

    def test_notes_never_deleted_by_clean(self, tmp_path):
        scaffold_codex(tmp_path)
        notes = tmp_path / "INSTITUTIONAL_KNOWLEDGE.md"
        notes.write_text("My custom notes")
        scaffold_codex(tmp_path, clean=True)
        assert notes.read_text() == "My custom notes"

    def test_notes_created_if_missing_on_clean(self, tmp_path):
        scaffold_codex(tmp_path, clean=True)
        assert (tmp_path / "INSTITUTIONAL_KNOWLEDGE.md").is_file()

    def test_notes_has_project_overview_section(self, tmp_path):
        scaffold_codex(tmp_path)
        content = (tmp_path / "INSTITUTIONAL_KNOWLEDGE.md").read_text()
        assert "# Institutional Notes" in content

    def test_notes_shared_across_tools(self, tmp_path):
        scaffold_codex(tmp_path)
        notes = tmp_path / "INSTITUTIONAL_KNOWLEDGE.md"
        notes.write_text("Custom notes")
        scaffold_opencode(tmp_path)
        assert notes.read_text() == "Custom notes"


class TestSkillsForConfig:
    def test_none_returns_all_skills(self):
        skills = skills_for_config(None, None)
        assert skills == CLAUDE_SKILL_DIRS

    def test_library_main_excludes_promote_and_service_skills(self):
        skills = skills_for_config(RepoType.LIBRARY, BranchStrategy.MAIN)
        assert "ai-promote" not in skills
        assert "ai-setup-oidc" not in skills
        assert "ai-standardize-repo" in skills
        assert "ai-init" in skills
        assert "ai-new-project" in skills

    def test_library_dev_includes_promote(self):
        skills = skills_for_config(RepoType.LIBRARY, BranchStrategy.DEV)
        assert "ai-promote" in skills

    def test_service_main_has_oidc_no_promote(self):
        skills = skills_for_config(RepoType.SERVICE, BranchStrategy.MAIN)
        assert "ai-setup-oidc" in skills
        assert "ai-promote" not in skills
        assert "ai-standardize-repo" in skills

    def test_service_dev_has_oidc_and_promote(self):
        skills = skills_for_config(RepoType.SERVICE, BranchStrategy.DEV)
        assert "ai-setup-oidc" in skills
        assert "ai-promote" in skills

    def test_workspace_has_workspace_skills(self):
        skills = skills_for_config(RepoType.WORKSPACE, BranchStrategy.MAIN)
        assert "ai-workspace-status" in skills
        assert "ai-workspace-sync" in skills
        assert "ai-workspace-init" in skills
        assert "ai-workspace-health" in skills
        assert "ai-workspace-foreach" in skills

    def test_workspace_excludes_service_skills(self):
        skills = skills_for_config(RepoType.WORKSPACE, BranchStrategy.MAIN)
        assert "ai-setup-oidc" not in skills
        assert "ai-promote" not in skills

    def test_deleted_skills_not_in_any_config(self):
        deleted = [
            "ai-standardize-precommit",
            "ai-standardize-pipeline",
            "ai-standardize-renovate",
            "ai-standardize-release",
            "ai-fix-repo-standards",
        ]
        for repo_type in RepoType:
            for branch_strategy in BranchStrategy:
                skills = skills_for_config(repo_type, branch_strategy)
                for name in deleted:
                    assert name not in skills, (
                        f"{name} should be deleted but found in {repo_type}/{branch_strategy}"
                    )

    def test_workspace_has_universal_skills(self):
        skills = skills_for_config(RepoType.WORKSPACE, BranchStrategy.MAIN)
        assert "ai-init" in skills
        assert "ai-pick-issue" in skills
        assert "ai-prepare-branch" in skills
        assert "ai-submit-work" in skills
        assert "ai-status" in skills
        assert "ai-standardize-repo" in skills
        assert "ai-new-project" in skills

    def test_all_types_have_universal_skills(self):
        for repo_type in RepoType:
            skills = skills_for_config(repo_type, BranchStrategy.MAIN)
            assert "ai-pick-issue" in skills
            assert "ai-prepare-branch" in skills
            assert "ai-submit-work" in skills
            assert "ai-monitor-pipeline" in skills
            assert "ai-status" in skills
            assert "ai-rollback" in skills
            assert "ai-repo-health" in skills
            assert "ai-standardize-repo" in skills
            assert "ai-standardize-dotfiles" in skills
            assert "ai-init" in skills
            assert "ai-new-project" in skills

    def test_ai_standardize_dotfiles_deploys_companion_files(self, tmp_path):
        scaffold_claude(tmp_path)
        skill_dir = tmp_path / ".claude" / "skills" / "ai-standardize-dotfiles"
        assert (skill_dir / "SKILL.md").is_file()
        assert (skill_dir / "gitignore-template").is_file()
        assert (skill_dir / "editorconfig-template").is_file()


class TestScaffoldWithRepoType:
    def test_claude_library_main_skills(self, tmp_path):
        scaffold_claude(
            tmp_path,
            repo_type=RepoType.LIBRARY,
            branch_strategy=BranchStrategy.MAIN,
        )
        skills_dir = tmp_path / ".claude" / "skills"
        assert not (skills_dir / "ai-promote").exists()
        assert not (skills_dir / "ai-setup-oidc").exists()
        assert not (skills_dir / "ai-workspace-status").exists()
        assert (skills_dir / "ai-init" / "SKILL.md").is_file()
        assert (skills_dir / "ai-pick-issue" / "SKILL.md").is_file()
        assert (skills_dir / "ai-standardize-repo" / "SKILL.md").is_file()
        assert (skills_dir / "ai-new-project" / "SKILL.md").is_file()
        # Deleted skills must not be deployed
        assert not (skills_dir / "ai-standardize-renovate").exists()
        assert not (skills_dir / "ai-fix-repo-standards").exists()

    def test_claude_service_dev_skills(self, tmp_path):
        scaffold_claude(
            tmp_path,
            repo_type=RepoType.SERVICE,
            branch_strategy=BranchStrategy.DEV,
        )
        skills_dir = tmp_path / ".claude" / "skills"
        assert (skills_dir / "ai-promote" / "SKILL.md").is_file()
        assert (skills_dir / "ai-setup-oidc" / "SKILL.md").is_file()
        assert not (skills_dir / "ai-workspace-status").exists()

    def test_claude_workspace_skills(self, tmp_path):
        scaffold_claude(
            tmp_path,
            repo_type=RepoType.WORKSPACE,
            branch_strategy=BranchStrategy.MAIN,
        )
        skills_dir = tmp_path / ".claude" / "skills"
        assert (skills_dir / "ai-workspace-status" / "SKILL.md").is_file()
        assert (skills_dir / "ai-workspace-sync" / "SKILL.md").is_file()
        assert (skills_dir / "ai-workspace-init" / "SKILL.md").is_file()
        assert (skills_dir / "ai-workspace-health" / "SKILL.md").is_file()
        assert (skills_dir / "ai-workspace-foreach" / "SKILL.md").is_file()
        assert not (skills_dir / "ai-promote").exists()

    def test_claude_none_delivers_all_original_skills(self, tmp_path):
        scaffold_claude(tmp_path, repo_type=None, branch_strategy=None)
        skills_dir = tmp_path / ".claude" / "skills"
        for skill_name in CLAUDE_SKILL_DIRS:
            assert (skills_dir / skill_name / "SKILL.md").is_file()

    def test_stale_skills_removed_on_type_change(self, tmp_path):
        # First scaffold with all skills
        scaffold_claude(
            tmp_path,
            repo_type=RepoType.SERVICE,
            branch_strategy=BranchStrategy.DEV,
        )
        skills_dir = tmp_path / ".claude" / "skills"
        assert (skills_dir / "ai-promote" / "SKILL.md").is_file()

        # Switch to workspace -- ai-promote should be removed
        scaffold_claude(
            tmp_path,
            overwrite=True,
            repo_type=RepoType.WORKSPACE,
            branch_strategy=BranchStrategy.MAIN,
        )
        assert not (skills_dir / "ai-promote").exists()
        assert (skills_dir / "ai-workspace-status" / "SKILL.md").is_file()

    def test_opencode_workspace_skills(self, tmp_path):
        scaffold_opencode(
            tmp_path,
            repo_type=RepoType.WORKSPACE,
            branch_strategy=BranchStrategy.MAIN,
        )
        skills_dir = tmp_path / ".agents" / "skills"
        assert (skills_dir / "ai-workspace-status" / "SKILL.md").is_file()
        assert not (skills_dir / "ai-promote").exists()

    def test_codex_library_skills(self, tmp_path):
        scaffold_codex(
            tmp_path,
            repo_type=RepoType.LIBRARY,
            branch_strategy=BranchStrategy.MAIN,
        )
        skills_dir = tmp_path / ".agents" / "skills"
        assert not (skills_dir / "ai-promote").exists()
        assert (skills_dir / "ai-pick-issue" / "SKILL.md").is_file()


class TestNotesTemplateSelection:
    def test_library_notes(self, tmp_path):
        scaffold_project(
            tmp_path,
            repo_type=RepoType.LIBRARY,
            branch_strategy=BranchStrategy.MAIN,
        )
        content = (tmp_path / "INSTITUTIONAL_KNOWLEDGE.md").read_text()
        assert "# Institutional Notes: Library Repos" in content
        assert "semantic-release" in content
        assert "ai-tools repo ..." in content
        assert "ai-tools standardize detect/audit/fix/verify" in content

    def test_service_notes(self, tmp_path):
        scaffold_project(
            tmp_path,
            repo_type=RepoType.SERVICE,
            branch_strategy=BranchStrategy.DEV,
        )
        content = (tmp_path / "INSTITUTIONAL_KNOWLEDGE.md").read_text()
        assert "# Institutional Notes: Service Repos" in content
        assert "merge-commit-only policy applies" in content
        assert "ai-tools repo ..." in content
        assert "ai-tools standardize detect/audit/fix/verify" in content

    def test_workspace_notes(self, tmp_path):
        scaffold_project(
            tmp_path,
            repo_type=RepoType.WORKSPACE,
            branch_strategy=BranchStrategy.MAIN,
        )
        content = (tmp_path / "INSTITUTIONAL_KNOWLEDGE.md").read_text()
        assert "# Institutional Notes: Workspaces" in content
        assert "ai-tools mono sync" in content
        assert "Workspace orchestration commands live under `ai-tools mono`" in content
        assert "ai-tools standardize ..." in content

    def test_none_type_uses_default_notes(self, tmp_path):
        scaffold_project(tmp_path, repo_type=None)
        content = (tmp_path / "INSTITUTIONAL_KNOWLEDGE.md").read_text()
        assert "# Institutional Notes" in content
        assert "## Submodule Map" not in content
        assert "## Publishing" not in content


class TestWorkspaceSkillCommandContract:
    def test_workspace_skills_use_ai_tools_mono_surface(self, tmp_path):
        scaffold_codex(
            tmp_path,
            repo_type=RepoType.WORKSPACE,
            branch_strategy=BranchStrategy.MAIN,
        )
        skills_dir = tmp_path / ".agents" / "skills"
        expected_commands = {
            "ai-workspace-init": "ai-tools mono sync --json",
            "ai-workspace-sync": "ai-tools mono sync --json",
            "ai-workspace-status": "ai-tools mono status --json",
            "ai-workspace-pick": "ai-tools mono issues --json",
            "ai-workspace-branch": "ai-tools mono branch --json",
            "ai-workspace-test": "ai-tools mono check --phase tests --json",
            "ai-workspace-lint": "ai-tools mono check --phase quality --json",
            "ai-workspace-submit": "ai-tools mono submit --json",
            "ai-workspace-update": "ai-tools mono update --json",
            "ai-workspace-health": "ai-tools mono status --actionable --json",
            "ai-workspace-foreach": "ai-tools mono foreach --json",
        }

        for skill_name, command in expected_commands.items():
            content = (skills_dir / skill_name / "SKILL.md").read_text()
            assert "augint-tools" not in content
            assert command in content


class TestProjectTomlContent:
    def test_library_toml_has_project_section(self, tmp_path):
        scaffold_project(
            tmp_path,
            repo_type=RepoType.LIBRARY,
            branch_strategy=BranchStrategy.MAIN,
        )
        content = (tmp_path / ".ai-shell.toml").read_text()
        assert 'repo_type = "library"' in content
        assert 'branch_strategy = "main"' in content
        # Active [project] section should not have dev_branch when strategy is main
        project_section = content.split("\n\n")[0]  # first block = [project]
        assert "dev_branch" not in project_section

    def test_service_dev_toml_has_dev_branch(self, tmp_path):
        scaffold_project(
            tmp_path,
            repo_type=RepoType.SERVICE,
            branch_strategy=BranchStrategy.DEV,
            dev_branch="staging",
        )
        content = (tmp_path / ".ai-shell.toml").read_text()
        assert 'repo_type = "service"' in content
        assert 'branch_strategy = "dev"' in content
        assert 'dev_branch = "staging"' in content

    def test_none_type_toml_no_project_section(self, tmp_path):
        scaffold_project(tmp_path, repo_type=None)
        content = (tmp_path / ".ai-shell.toml").read_text()
        assert "[project]" not in content or "# [project]" in content


class TestRepoTypeCompat:
    """Verify repo-type config loading behavior."""

    def test_workspace_kept_in_config(self, tmp_path):
        from ai_shell.config import load_config

        toml_content = '[project]\nrepo_type = "workspace"\n'
        (tmp_path / ".ai-shell.toml").write_text(toml_content)
        config = load_config(project_dir=tmp_path)
        assert config.repo_type == "workspace"

    def test_service_stays_service_in_config(self, tmp_path):
        from ai_shell.config import load_config

        toml_content = '[project]\nrepo_type = "service"\n'
        (tmp_path / ".ai-shell.toml").write_text(toml_content)
        config = load_config(project_dir=tmp_path)
        assert config.repo_type == "service"

    def test_library_stays_library_in_config(self, tmp_path):
        from ai_shell.config import load_config

        toml_content = '[project]\nrepo_type = "library"\n'
        (tmp_path / ".ai-shell.toml").write_text(toml_content)
        config = load_config(project_dir=tmp_path)
        assert config.repo_type == "library"
