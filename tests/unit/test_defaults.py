"""Tests for ai_shell.defaults module."""

from pathlib import Path
from unittest.mock import patch

from ai_shell.defaults import (
    CONTAINER_PREFIX,
    UV_CACHE_VOLUME,
    build_dev_environment,
    build_dev_mounts,
    dev_container_name,
    sanitize_project_name,
)


class TestSanitizeProjectName:
    def test_simple_name(self):
        assert sanitize_project_name(Path("/home/user/my-project")) == "my-project"

    def test_uppercase_converted(self):
        assert sanitize_project_name(Path("/home/user/MyProject")) == "myproject"

    def test_spaces_become_hyphens(self):
        assert sanitize_project_name(Path("/home/user/my project")) == "my-project"

    def test_special_chars_replaced(self):
        assert sanitize_project_name(Path("/home/user/my_project.v2")) == "my-project-v2"

    def test_multiple_hyphens_collapsed(self):
        assert sanitize_project_name(Path("/home/user/my---project")) == "my-project"

    def test_leading_trailing_hyphens_stripped(self):
        assert sanitize_project_name(Path("/home/user/--project--")) == "project"

    def test_empty_name_returns_project(self):
        assert sanitize_project_name(Path("/")) == "project"

    def test_dots_only_returns_project(self):
        # Path(".").resolve() gives absolute path, basename is real dir name
        # But Path("/...") basename is "..."
        assert sanitize_project_name(Path("/...")) == "project"


class TestDevContainerName:
    def test_basic(self):
        assert dev_container_name("my-project") == f"{CONTAINER_PREFIX}-my-project-dev"


class TestBuildDevMounts:
    def test_always_includes_project_dir(self, tmp_path):
        project_dir = tmp_path / "test-project"
        project_dir.mkdir()

        mounts = build_dev_mounts(project_dir, "test-project")

        # First mount should be the project directory
        assert mounts[0].get("Target") == "/root/projects/test-project"
        assert mounts[0].get("Source") == str(project_dir.resolve())

    def test_includes_uv_cache_volume(self, tmp_path):
        project_dir = tmp_path / "test-project"
        project_dir.mkdir()

        mounts = build_dev_mounts(project_dir, "test-project")

        # Find the uv-cache volume mount
        uv_mount = None
        for m in mounts:
            if m.get("Target") == "/root/.cache/uv":
                uv_mount = m
                break

        assert uv_mount is not None
        assert uv_mount.get("Source") == UV_CACHE_VOLUME

    def test_skips_missing_optional_paths(self, tmp_path):
        project_dir = tmp_path / "test-project"
        project_dir.mkdir()

        # With a fake home that has nothing in it
        with patch("ai_shell.defaults.Path.home", return_value=tmp_path / "fakehome"):
            (tmp_path / "fakehome").mkdir()
            mounts = build_dev_mounts(project_dir, "test-project")

        # Should have project dir + uv-cache volume, but no optional mounts
        targets = [m.get("Target") for m in mounts]
        assert "/root/projects/test-project" in targets
        assert "/root/.cache/uv" in targets
        # Optional mounts should NOT be present since paths don't exist
        assert "/root/.ssh" not in targets
        assert "/root/.claude" not in targets

    def test_includes_existing_optional_paths(self, tmp_path):
        project_dir = tmp_path / "test-project"
        project_dir.mkdir()

        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        (fake_home / ".ssh").mkdir()
        (fake_home / ".claude").mkdir()
        (fake_home / ".aws").mkdir()

        with patch("ai_shell.defaults.Path.home", return_value=fake_home):
            mounts = build_dev_mounts(project_dir, "test-project")

        targets = [m.get("Target") for m in mounts]
        assert "/root/.ssh" in targets
        assert "/root/.claude" in targets
        assert "/root/.aws" in targets


class TestBuildDevEnvironment:
    def test_includes_sandbox_flag(self):
        env = build_dev_environment()
        assert env["IS_SANDBOX"] == "1"

    def test_includes_aws_region_default(self):
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment()
        assert env["AWS_REGION"] == "us-east-1"

    def test_passes_through_gh_token(self):
        with patch.dict("os.environ", {"GH_TOKEN": "test-token"}):
            env = build_dev_environment()
        assert env["GH_TOKEN"] == "test-token"
        assert env["GITHUB_TOKEN"] == "test-token"

    def test_passes_through_aws_profile(self):
        with patch.dict("os.environ", {"AWS_PROFILE": "my-sso-profile"}):
            env = build_dev_environment()
        assert env["AWS_PROFILE"] == "my-sso-profile"

    def test_aws_iam_keys_not_passed(self):
        with patch.dict(
            "os.environ",
            {"AWS_ACCESS_KEY_ID": "AKIA-test", "AWS_SECRET_ACCESS_KEY": "secret"},
        ):
            env = build_dev_environment()
        assert "AWS_ACCESS_KEY_ID" not in env
        assert "AWS_SECRET_ACCESS_KEY" not in env
        assert "AWS_SESSION_TOKEN" not in env

    def test_extra_env_merged(self):
        env = build_dev_environment(extra_env={"CUSTOM_VAR": "custom_value"})
        assert env["CUSTOM_VAR"] == "custom_value"
        assert env["IS_SANDBOX"] == "1"  # originals still present


class TestBuildDevEnvironmentDotenv:
    def test_loads_gh_token_from_dotenv(self, tmp_path):
        (tmp_path / ".env").write_text("GH_TOKEN=from-dotenv\n")
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(project_dir=tmp_path)
        assert env["GH_TOKEN"] == "from-dotenv"
        assert env["GITHUB_TOKEN"] == "from-dotenv"

    def test_dotenv_overrides_os_environ(self, tmp_path):
        (tmp_path / ".env").write_text("GH_TOKEN=from-dotenv\n")
        with patch.dict("os.environ", {"GH_TOKEN": "from-os"}):
            env = build_dev_environment(project_dir=tmp_path)
        assert env["GH_TOKEN"] == "from-dotenv"

    def test_extra_env_overrides_dotenv(self, tmp_path):
        (tmp_path / ".env").write_text("GH_TOKEN=from-dotenv\n")
        env = build_dev_environment(
            extra_env={"GH_TOKEN": "from-config"},
            project_dir=tmp_path,
        )
        assert env["GH_TOKEN"] == "from-config"

    def test_falls_back_to_os_environ_when_not_in_dotenv(self, tmp_path):
        (tmp_path / ".env").write_text("OTHER_VAR=other\n")
        with patch.dict("os.environ", {"GH_TOKEN": "from-os"}):
            env = build_dev_environment(project_dir=tmp_path)
        assert env["GH_TOKEN"] == "from-os"

    def test_no_project_dir_uses_old_behavior(self):
        with patch.dict("os.environ", {"GH_TOKEN": "from-os"}):
            env = build_dev_environment()
        assert env["GH_TOKEN"] == "from-os"

    def test_missing_dotenv_uses_defaults(self, tmp_path):
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(project_dir=tmp_path)
        assert env["GH_TOKEN"] == ""
        assert env["AWS_REGION"] == "us-east-1"

    def test_dotenv_aws_region(self, tmp_path):
        (tmp_path / ".env").write_text("AWS_REGION=eu-west-1\n")
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(project_dir=tmp_path)
        assert env["AWS_REGION"] == "eu-west-1"


class TestBuildDevEnvironmentBedrock:
    def test_bedrock_adds_env_var(self):
        env = build_dev_environment(bedrock=True)
        assert env["CLAUDE_CODE_USE_BEDROCK"] == "1"

    def test_no_bedrock_no_env_var(self):
        env = build_dev_environment()
        assert "CLAUDE_CODE_USE_BEDROCK" not in env

    def test_bedrock_false_no_env_var(self):
        env = build_dev_environment(bedrock=False)
        assert "CLAUDE_CODE_USE_BEDROCK" not in env

    def test_bedrock_profile_overrides_aws_profile(self):
        with patch.dict("os.environ", {"AWS_PROFILE": "infra-acct"}, clear=True):
            env = build_dev_environment(bedrock=True, bedrock_profile="ai-acct")
        assert env["AWS_PROFILE"] == "ai-acct"
        assert env["CLAUDE_CODE_USE_BEDROCK"] == "1"

    def test_bedrock_without_bedrock_profile_keeps_aws_profile(self):
        with patch.dict("os.environ", {"AWS_PROFILE": "infra-acct"}, clear=True):
            env = build_dev_environment(bedrock=True)
        assert env["AWS_PROFILE"] == "infra-acct"

    def test_aws_profile_override(self):
        with patch.dict("os.environ", {"AWS_PROFILE": "original"}, clear=True):
            env = build_dev_environment(aws_profile="override")
        assert env["AWS_PROFILE"] == "override"

    def test_aws_region_override(self):
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(aws_region="eu-west-1")
        assert env["AWS_REGION"] == "eu-west-1"

    def test_aws_profile_empty_uses_resolved(self):
        with patch.dict("os.environ", {"AWS_PROFILE": "from-env"}, clear=True):
            env = build_dev_environment(aws_profile="")
        assert env["AWS_PROFILE"] == "from-env"

    def test_bedrock_profile_only_applies_when_bedrock_enabled(self):
        with patch.dict("os.environ", {"AWS_PROFILE": "infra"}, clear=True):
            env = build_dev_environment(bedrock=False, bedrock_profile="ai-acct")
        assert env["AWS_PROFILE"] == "infra"
        assert "CLAUDE_CODE_USE_BEDROCK" not in env
