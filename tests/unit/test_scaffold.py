"""Tests for ai_shell.scaffold module."""

import json

import yaml

from ai_shell.scaffold import (
    _deep_merge_settings,
    scaffold_aider,
    scaffold_claude,
    scaffold_codex,
    scaffold_opencode,
    scaffold_project,
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

    def test_does_not_create_skills(self, tmp_path):
        """Skills are now delivered via the augint-workflow plugin."""
        scaffold_claude(tmp_path)
        assert not (tmp_path / ".claude" / "skills").exists()

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


class TestScaffoldProject:
    def test_creates_yaml(self, tmp_path):
        scaffold_project(tmp_path)
        assert (tmp_path / ".ai-shell.yaml").is_file()
        # opencode.json is no longer created by scaffold_project
        assert not (tmp_path / "opencode.json").exists()

    def test_yaml_has_commented_sections(self, tmp_path):
        scaffold_project(tmp_path)
        content = (tmp_path / ".ai-shell.yaml").read_text()
        assert "# container:" in content or "container:" in content
        assert "# llm:" in content or "llm:" in content
        assert "# aider:" in content or "aider:" in content

    def test_init_skips_existing(self, tmp_path):
        (tmp_path / ".ai-shell.yaml").write_text("original")
        scaffold_project(tmp_path, overwrite=False)
        assert (tmp_path / ".ai-shell.yaml").read_text() == "original"

    def test_reset_overwrites_existing(self, tmp_path):
        (tmp_path / ".ai-shell.yaml").write_text("original")
        scaffold_project(tmp_path, overwrite=True)
        assert (tmp_path / ".ai-shell.yaml").read_text() != "original"

    def test_update_overwrites_yaml(self, tmp_path):
        (tmp_path / ".ai-shell.yaml").write_text("original")
        scaffold_project(tmp_path, merge=True)
        assert (tmp_path / ".ai-shell.yaml").read_text() != "original"

    def test_clean_removes_and_recreates(self, tmp_path):
        scaffold_project(tmp_path)
        scaffold_project(tmp_path, clean=True)
        assert (tmp_path / ".ai-shell.yaml").is_file()

    def test_clean_works_on_empty_dir(self, tmp_path):
        scaffold_project(tmp_path, clean=True)
        assert (tmp_path / ".ai-shell.yaml").is_file()


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
        scaffold_opencode(tmp_path, clean=True)
        assert (tmp_path / "opencode.json").is_file()

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
        assert (tmp_path / ".aiderignore").is_file()

    def test_clean_works_on_empty_dir(self, tmp_path):
        scaffold_aider(tmp_path, clean=True)
        assert (tmp_path / ".aider.conf.yml").is_file()


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
        import yaml

        parsed = yaml.safe_load(content)
        # All content is commented out, so parsed should be None
        assert parsed is None
