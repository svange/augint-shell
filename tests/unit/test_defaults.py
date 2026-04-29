"""Tests for ai_shell.defaults module."""

from pathlib import Path
from unittest.mock import patch

import pytest

from ai_shell.defaults import (
    CONTAINER_PREFIX,
    DEV_PORT_RANGE_SIZE,
    DEV_PORT_RANGE_START,
    GH_CONFIG_VOLUME,
    N8N_DATA_VOLUME,
    NPM_CACHE_VOLUME,
    OLLAMA_CONTAINER,
    PRE_COMMIT_CACHE_PATH,
    PRE_COMMIT_CACHE_VOLUME,
    UV_CACHE_VOLUME,
    build_dev_environment,
    build_dev_mounts,
    build_n8n_environment,
    build_n8n_mounts,
    dev_container_name,
    project_dev_port,
    sanitize_project_name,
    unique_project_name,
    uv_venv_path,
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

    def test_uses_path_hash_when_project_dir_provided(self):
        project_dir = Path("/home/user/projects/workspace/my-project")
        expected = unique_project_name(project_dir, "my-project")
        assert dev_container_name("my-project", project_dir) == f"{CONTAINER_PREFIX}-{expected}-dev"

    def test_same_leaf_name_different_paths_do_not_collide(self):
        root = dev_container_name("woxom-infra", Path("/home/user/projects/woxom-infra"))
        nested = dev_container_name(
            "woxom-infra",
            Path("/home/user/projects/woxom-ecosystem/woxom-infra"),
        )
        assert root != nested


class TestProjectDevPort:
    def test_deterministic(self, tmp_path):
        port1 = project_dev_port(tmp_path, 3000)
        port2 = project_dev_port(tmp_path, 3000)
        assert port1 == port2

    def test_in_range(self, tmp_path):
        port = project_dev_port(tmp_path, 3000)
        assert DEV_PORT_RANGE_START <= port < DEV_PORT_RANGE_START + DEV_PORT_RANGE_SIZE

    def test_differs_per_project(self, tmp_path):
        dir_a = tmp_path / "project-a"
        dir_b = tmp_path / "project-b"
        dir_a.mkdir()
        dir_b.mkdir()
        assert project_dev_port(dir_a, 3000) != project_dev_port(dir_b, 3000)

    def test_differs_per_container_port(self, tmp_path):
        assert project_dev_port(tmp_path, 3000) != project_dev_port(tmp_path, 5173)

    def test_accepts_project_name_override(self, tmp_path):
        port_default = project_dev_port(tmp_path, 3000)
        port_named = project_dev_port(tmp_path, 3000, project_name="custom")
        assert port_default != port_named

    def test_stable_across_calls_with_name(self, tmp_path):
        port1 = project_dev_port(tmp_path, 8080, project_name="my-app")
        port2 = project_dev_port(tmp_path, 8080, project_name="my-app")
        assert port1 == port2


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

    def test_includes_npm_cache_volume(self, tmp_path):
        project_dir = tmp_path / "test-project"
        project_dir.mkdir()

        mounts = build_dev_mounts(project_dir, "test-project")

        npm_mount = None
        for m in mounts:
            if m.get("Target") == "/root/.npm":
                npm_mount = m
                break

        assert npm_mount is not None
        assert npm_mount.get("Source") == NPM_CACHE_VOLUME

    def test_includes_pre_commit_cache_volume(self, tmp_path):
        project_dir = tmp_path / "test-project"
        project_dir.mkdir()

        mounts = build_dev_mounts(project_dir, "test-project")

        pc_mount = None
        for m in mounts:
            if m.get("Target") == PRE_COMMIT_CACHE_PATH:
                pc_mount = m
                break

        assert pc_mount is not None
        assert pc_mount.get("Source") == PRE_COMMIT_CACHE_VOLUME
        assert pc_mount.get("Type") == "volume"

    def test_skips_missing_optional_paths(self, tmp_path):
        project_dir = tmp_path / "test-project"
        project_dir.mkdir()

        # With a fake home that has nothing in it
        with (
            patch("ai_shell.defaults.Path.home", return_value=tmp_path / "fakehome"),
            patch.dict("os.environ", {}, clear=True),
        ):
            (tmp_path / "fakehome").mkdir()
            mounts = build_dev_mounts(project_dir, "test-project")

        targets = [m.get("Target") for m in mounts]
        assert "/root/projects/test-project" in targets
        assert "/root/.cache/uv" in targets
        assert "/root/.npm" in targets
        assert PRE_COMMIT_CACHE_PATH in targets
        assert "/root/.ssh" not in targets
        assert "/root/.claude" not in targets
        # No host path found → falls back to named volume (not a bind mount)
        gh_mount = next((m for m in mounts if m.get("Target") == "/root/.config/gh"), None)
        assert gh_mount is not None
        assert gh_mount.get("Type") == "volume"
        assert gh_mount.get("Source") == GH_CONFIG_VOLUME

    def test_includes_existing_optional_paths(self, tmp_path):
        project_dir = tmp_path / "test-project"
        project_dir.mkdir()

        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        (fake_home / ".ssh").mkdir()
        (fake_home / ".claude").mkdir()
        (fake_home / ".aws").mkdir()
        (fake_home / ".config" / "gh").mkdir(parents=True)

        with (
            patch("ai_shell.defaults.Path.home", return_value=fake_home),
            patch.dict("os.environ", {}, clear=True),
        ):
            mounts = build_dev_mounts(project_dir, "test-project")

        targets = [m.get("Target") for m in mounts]
        assert "/root/.ssh" in targets
        assert "/root/.claude" in targets
        assert "/root/.aws" in targets
        # Host path found → bind mount (not named volume)
        gh_mount = next((m for m in mounts if m.get("Target") == "/root/.config/gh"), None)
        assert gh_mount is not None
        assert gh_mount.get("Type") == "bind"


class TestBuildDevEnvironment:
    def test_includes_sandbox_flag(self):
        env = build_dev_environment()
        assert env["IS_SANDBOX"] == "1"

    def test_sets_pre_commit_home(self):
        env = build_dev_environment()
        assert env["PRE_COMMIT_HOME"] == PRE_COMMIT_CACHE_PATH

    def test_includes_aws_region_default(self):
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment()
        assert env["AWS_REGION"] == "us-east-1"

    def test_gh_token_not_injected_by_default(self):
        with patch.dict("os.environ", {"GH_TOKEN": "test-token"}):
            env = build_dev_environment()
        assert "GH_TOKEN" not in env
        assert "GITHUB_TOKEN" not in env

    def test_gh_token_injected_with_env_file(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("GH_TOKEN=test-token\n")
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(env_file=env_file)
        assert env["GH_TOKEN"] == "test-token"
        # GITHUB_TOKEN is no longer auto-mirrored — put it in .env explicitly.
        assert "GITHUB_TOKEN" not in env

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
    def test_loads_gh_token_from_dotenv_with_env_flag(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("GH_TOKEN=from-dotenv\n")
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(project_dir=tmp_path, env_file=env_file)
        assert env["GH_TOKEN"] == "from-dotenv"
        assert "GITHUB_TOKEN" not in env

    def test_dotenv_overrides_os_environ_with_env_flag(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("GH_TOKEN=from-dotenv\n")
        with patch.dict("os.environ", {"GH_TOKEN": "from-os"}):
            env = build_dev_environment(project_dir=tmp_path, env_file=env_file)
        assert env["GH_TOKEN"] == "from-dotenv"

    def test_extra_env_overrides_dotenv(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("GH_TOKEN=from-dotenv\n")
        env = build_dev_environment(
            extra_env={"GH_TOKEN": "from-config"},
            project_dir=tmp_path,
            env_file=env_file,
        )
        assert env["GH_TOKEN"] == "from-config"

    def test_no_gh_token_without_env_flag(self, tmp_path):
        (tmp_path / ".env").write_text("OTHER_VAR=other\n")
        with patch.dict("os.environ", {"GH_TOKEN": "from-os"}):
            env = build_dev_environment(project_dir=tmp_path)
        assert "GH_TOKEN" not in env

    def test_missing_dotenv_uses_defaults(self, tmp_path):
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(project_dir=tmp_path)
        assert "GH_TOKEN" not in env
        assert env["AWS_REGION"] == "us-east-1"

    def test_dotenv_aws_region(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("AWS_REGION=eu-west-1\n")
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(project_dir=tmp_path, env_file=env_file)
        assert env["AWS_REGION"] == "eu-west-1"

    def test_arbitrary_dotenv_var_passes_through_with_env_flag(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("PI_STUDIO_PORT=8888\n")
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(project_dir=tmp_path, env_file=env_file)
        assert env["PI_STUDIO_PORT"] == "8888"

    def test_arbitrary_dotenv_var_blocked_without_env_flag(self, tmp_path):
        (tmp_path / ".env").write_text("PI_STUDIO_PORT=8888\n")
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(project_dir=tmp_path)
        assert "PI_STUDIO_PORT" not in env

    def test_global_augint_env_always_loaded(self, isolate_home):
        global_env = isolate_home / ".augint" / ".env"
        global_env.parent.mkdir(parents=True, exist_ok=True)
        global_env.write_text("MY_GLOBAL_VAR=hello\n")
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment()
        assert env["MY_GLOBAL_VAR"] == "hello"

    def test_cli_flag_beats_dotenv(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("AWS_PROFILE=from-env\n")
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(
                project_dir=tmp_path, env_file=env_file, aws_profile="cli-wins"
            )
        assert env["AWS_PROFILE"] == "cli-wins"


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

    def test_aws_default_region_mirrors_aws_region(self):
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(aws_region="eu-west-1")
        assert env["AWS_DEFAULT_REGION"] == "eu-west-1"
        assert env["AWS_DEFAULT_REGION"] == env["AWS_REGION"]

    def test_aws_default_region_default(self):
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment()
        assert env["AWS_DEFAULT_REGION"] == "us-east-1"
        assert env["AWS_DEFAULT_REGION"] == env["AWS_REGION"]

    def test_bedrock_region_overrides_aws_region_when_bedrock(self):
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(
                bedrock=True, aws_region="us-east-1", bedrock_region="us-gov-west-1"
            )
        assert env["AWS_REGION"] == "us-gov-west-1"
        assert env["AWS_DEFAULT_REGION"] == "us-gov-west-1"

    def test_bedrock_region_ignored_when_not_bedrock(self):
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(
                bedrock=False, aws_region="us-east-1", bedrock_region="us-gov-west-1"
            )
        assert env["AWS_REGION"] == "us-east-1"

    def test_bedrock_region_falls_back_to_env_var(self):
        with patch.dict("os.environ", {"AWS_BEDROCK_REGION": "eu-west-1"}, clear=True):
            env = build_dev_environment(bedrock=True)
        assert env["AWS_REGION"] == "eu-west-1"
        assert env["AWS_DEFAULT_REGION"] == "eu-west-1"

    def test_bedrock_region_falls_back_to_aws_region(self):
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(bedrock=True, aws_region="us-west-2")
        assert env["AWS_REGION"] == "us-west-2"

    def test_bedrock_region_config_wins_over_env(self):
        with patch.dict("os.environ", {"AWS_BEDROCK_REGION": "eu-west-1"}, clear=True):
            env = build_dev_environment(bedrock=True, bedrock_region="us-gov-west-1")
        assert env["AWS_REGION"] == "us-gov-west-1"


class TestBuildDevEnvironmentOpenAIProfile:
    def test_openai_profile_sets_api_key(self, tmp_path):
        dotenv_path = tmp_path / ".env"
        dotenv_path.write_text("OPENAI_API_KEY_AILLC=sk-test-123\n")
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(
                project_dir=tmp_path, env_file=dotenv_path, openai_profile="aillc"
            )
        assert env["OPENAI_API_KEY"] == "sk-test-123"

    def test_openai_profile_sets_org_id_when_present(self, tmp_path):
        dotenv_path = tmp_path / ".env"
        dotenv_path.write_text("OPENAI_API_KEY_AILLC=sk-test-123\nOPENAI_ORG_ID_AILLC=org-abc\n")
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(
                project_dir=tmp_path, env_file=dotenv_path, openai_profile="aillc"
            )
        assert env["OPENAI_API_KEY"] == "sk-test-123"
        assert env["OPENAI_ORG_ID"] == "org-abc"

    def test_openai_profile_no_org_id(self, tmp_path):
        dotenv_path = tmp_path / ".env"
        dotenv_path.write_text("OPENAI_API_KEY_PERSONAL=sk-personal\n")
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(
                project_dir=tmp_path, env_file=dotenv_path, openai_profile="personal"
            )
        assert env["OPENAI_API_KEY"] == "sk-personal"
        assert "OPENAI_ORG_ID" not in env

    def test_openai_profile_uppercases_name(self, tmp_path):
        dotenv_path = tmp_path / ".env"
        dotenv_path.write_text("OPENAI_API_KEY_MYACCT=sk-myacct\n")
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(
                project_dir=tmp_path, env_file=dotenv_path, openai_profile="myacct"
            )
        assert env["OPENAI_API_KEY"] == "sk-myacct"

    def test_openai_profile_missing_key_raises(self, tmp_path):
        dotenv_path = tmp_path / ".env"
        dotenv_path.write_text("OPENAI_API_KEY_OTHER=sk-other\n")
        with pytest.raises(ValueError, match="OPENAI_API_KEY_AILLC"):
            build_dev_environment(
                project_dir=tmp_path, env_file=dotenv_path, openai_profile="aillc"
            )

    def test_openai_profile_empty_string_is_noop(self):
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(openai_profile="")
        assert "OPENAI_API_KEY" not in env
        assert "OPENAI_ORG_ID" not in env


class TestUvVenvPath:
    def test_basic_repo_name(self):
        assert uv_venv_path("my-project") == "/root/.cache/uv/venvs/my-project"

    def test_with_worktree(self):
        assert (
            uv_venv_path("my-project", worktree_name="feat-1")
            == "/root/.cache/uv/venvs/my-project-wt-feat-1"
        )

    def test_worktree_none(self):
        assert uv_venv_path("repo", worktree_name=None) == "/root/.cache/uv/venvs/repo"

    def test_used_by_build_dev_environment(self):
        env = build_dev_environment(project_name="test-proj")
        assert env["UV_PROJECT_ENVIRONMENT"] == uv_venv_path("test-proj")


class TestBuildDevEnvironmentTeamMode:
    def test_team_mode_sets_agent_teams_env(self):
        env = build_dev_environment(team_mode=True)
        assert env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] == "1"

    def test_no_team_mode_no_agent_teams_env(self):
        env = build_dev_environment()
        assert "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" not in env

    def test_team_mode_false_no_agent_teams_env(self):
        env = build_dev_environment(team_mode=False)
        assert "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" not in env


class TestBuildDevEnvironmentGhToken:
    def test_gh_config_dir_does_not_set_gh_token(self, tmp_path):
        gh_dir = tmp_path / ".config" / "gh"
        gh_dir.mkdir(parents=True)
        (gh_dir / "hosts.yml").write_text("github.com:\n  oauth_token: ghp_from_hosts\n")
        with (
            patch("ai_shell.defaults.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {}, clear=True),
        ):
            env = build_dev_environment()
        assert "GH_TOKEN" not in env

    def test_dotenv_gh_token_used_with_env_file(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("GH_TOKEN=ghp_from_dotenv\n")
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment(project_dir=tmp_path, env_file=env_file)
        assert env["GH_TOKEN"] == "ghp_from_dotenv"
        assert "GITHUB_TOKEN" not in env

    def test_os_environ_gh_token_not_used_without_env_file(self):
        with patch.dict("os.environ", {"GH_TOKEN": "ghp_from_env"}):
            env = build_dev_environment()
        assert "GH_TOKEN" not in env


class TestBuildDevEnvironmentPath:
    def test_path_includes_opencode_bin(self):
        env = build_dev_environment()
        assert "PATH" in env
        assert "/root/.opencode/bin" in env["PATH"]

    def test_path_includes_local_bin(self):
        env = build_dev_environment()
        assert "/root/.local/bin" in env["PATH"]

    def test_path_includes_standard_dirs(self):
        env = build_dev_environment()
        assert "/usr/local/bin" in env["PATH"]
        assert "/usr/bin" in env["PATH"]


class TestBuildDevEnvironmentLayeredDotenv:
    def test_global_env_loaded(self, tmp_path):
        augint_dir = tmp_path / ".augint"
        augint_dir.mkdir()
        (augint_dir / ".env").write_text("AWS_REGION=from-global\n")
        with (
            patch("ai_shell.defaults.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {}, clear=True),
        ):
            env = build_dev_environment()
        assert env["AWS_REGION"] == "from-global"

    def test_project_env_overrides_global_with_env_flag(self, tmp_path):
        augint_dir = tmp_path / ".augint"
        augint_dir.mkdir()
        (augint_dir / ".env").write_text("AWS_REGION=from-global\n")
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        project_env = project_dir / ".env"
        project_env.write_text("AWS_REGION=from-project\n")
        with (
            patch("ai_shell.defaults.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {}, clear=True),
        ):
            env = build_dev_environment(project_dir=project_dir, env_file=project_env)
        assert env["AWS_REGION"] == "from-project"

    def test_project_env_ignored_without_env_flag(self, tmp_path):
        augint_dir = tmp_path / ".augint"
        augint_dir.mkdir()
        (augint_dir / ".env").write_text("AWS_REGION=from-global\n")
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / ".env").write_text("AWS_REGION=from-project\n")
        with (
            patch("ai_shell.defaults.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {}, clear=True),
        ):
            env = build_dev_environment(project_dir=project_dir)
        assert env["AWS_REGION"] == "from-global"

    def test_dotenv_overrides_os_environ(self, tmp_path):
        augint_dir = tmp_path / ".augint"
        augint_dir.mkdir()
        (augint_dir / ".env").write_text("AWS_REGION=from-global\n")
        with (
            patch("ai_shell.defaults.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {"AWS_REGION": "from-os"}),
        ):
            env = build_dev_environment()
        assert env["AWS_REGION"] == "from-global"

    def test_missing_global_env_is_graceful(self, tmp_path):
        with (
            patch("ai_shell.defaults.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {"AWS_REGION": "from-os"}),
        ):
            env = build_dev_environment()
        assert env["AWS_REGION"] == "from-os"


class TestBuildDevEnvironmentSharedPassthrough:
    def test_shared_vars_passed_through(self, tmp_path):
        augint_dir = tmp_path / ".augint"
        augint_dir.mkdir()
        (augint_dir / ".env").write_text(
            "PRIMARY_CHAT_MODEL=qwen3.5:27b\nOLLAMA_PORT=11434\nANTHROPIC_API_KEY=sk-ant-test\n"
        )
        with (
            patch("ai_shell.defaults.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {}, clear=True),
        ):
            env = build_dev_environment()
        assert env["PRIMARY_CHAT_MODEL"] == "qwen3.5:27b"
        assert env["OLLAMA_PORT"] == "11434"
        assert env["ANTHROPIC_API_KEY"] == "sk-ant-test"

    def test_shared_vars_omitted_when_empty(self):
        with patch.dict("os.environ", {}, clear=True):
            env = build_dev_environment()
        assert "PRIMARY_CHAT_MODEL" not in env
        assert "OLLAMA_PORT" not in env
        assert "ANTHROPIC_API_KEY" not in env


class TestFindGhConfigDir:
    def test_linux_path_preferred(self, tmp_path):
        from ai_shell.defaults import _find_gh_config_dir

        linux_gh = tmp_path / ".config" / "gh"
        linux_gh.mkdir(parents=True)
        with (
            patch("ai_shell.defaults.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = _find_gh_config_dir()
        assert result == linux_gh

    def test_returns_none_when_nothing_exists(self, tmp_path):
        from ai_shell.defaults import _find_gh_config_dir

        with (
            patch("ai_shell.defaults.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = _find_gh_config_dir()
        assert result is None

    def test_wsl2_appdata_not_set_returns_none(self, tmp_path):
        from ai_shell.defaults import _find_gh_config_dir

        with (
            patch("ai_shell.defaults.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = _find_gh_config_dir()
        assert result is None

    def test_wsl2_appdata_path_no_drive_letter_skipped(self, tmp_path):
        from ai_shell.defaults import _find_gh_config_dir

        # APPDATA without a colon (not a Windows path) should be ignored
        with (
            patch("ai_shell.defaults.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {"APPDATA": "/some/linux/path"}, clear=True),
        ):
            result = _find_gh_config_dir()
        assert result is None


class TestBuildN8nEnvironment:
    def test_always_sets_n8n_secure_cookie(self):
        with patch.dict("os.environ", {}, clear=True):
            env = build_n8n_environment()
        assert env["N8N_SECURE_COOKIE"] == "false"

    def test_includes_service_discovery_urls(self):
        with patch.dict("os.environ", {}, clear=True):
            env = build_n8n_environment()
        assert env["OLLAMA_BASE_URL"] == f"http://{OLLAMA_CONTAINER}:11434"
        assert "KOKORO_BASE_URL" in env
        assert "WHISPER_BASE_URL" in env
        assert "VOICE_AGENT_BASE_URL" in env
        assert "WEBUI_BASE_URL" in env
        assert "COMFYUI_BASE_URL" in env
        assert env["COMFYUI_BASE_URL"].endswith(":8188")

    def test_uses_internal_container_ports(self):
        with patch.dict("os.environ", {}, clear=True):
            env = build_n8n_environment()
        # Must use container hostnames, not localhost
        for key in ("OLLAMA_BASE_URL", "KOKORO_BASE_URL", "WHISPER_BASE_URL"):
            assert "localhost" not in env[key]

    def test_passes_through_openai_key(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=True):
            env = build_n8n_environment()
        assert env["OPENAI_API_KEY"] == "sk-test"

    def test_passes_through_anthropic_key(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test"}, clear=True):
            env = build_n8n_environment()
        assert env["ANTHROPIC_API_KEY"] == "sk-ant-test"

    def test_omits_keys_when_not_in_environment(self):
        with patch.dict("os.environ", {}, clear=True):
            env = build_n8n_environment()
        assert "OPENAI_API_KEY" not in env
        assert "ANTHROPIC_API_KEY" not in env
        assert "GH_TOKEN" not in env

    def test_gh_token_sets_github_models_url(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("GH_TOKEN=ghp_test\n")
        with patch.dict("os.environ", {}, clear=True):
            env = build_n8n_environment(env_file=env_file)
        assert env["GH_TOKEN"] == "ghp_test"
        assert env["GITHUB_TOKEN"] == "ghp_test"
        assert env["GITHUB_MODELS_BASE_URL"] == "https://models.inference.ai.azure.com"

    def test_aws_profile_and_region(self):
        with patch.dict("os.environ", {}, clear=True):
            env = build_n8n_environment(aws_profile="my-profile", aws_region="eu-west-1")
        assert env["AWS_PROFILE"] == "my-profile"
        assert env["AWS_REGION"] == "eu-west-1"
        assert env["AWS_DEFAULT_REGION"] == "eu-west-1"

    def test_aws_profile_empty_omitted(self):
        with patch.dict("os.environ", {}, clear=True):
            env = build_n8n_environment()
        assert "AWS_PROFILE" not in env

    def test_loads_from_env_file(self, tmp_path):
        env_file = tmp_path / ".env.augint-shell"
        env_file.write_text("OPENAI_API_KEY=sk-from-file\nGH_TOKEN=ghp_file\n")
        with patch.dict("os.environ", {}, clear=True):
            env = build_n8n_environment(env_file=env_file)
        assert env["OPENAI_API_KEY"] == "sk-from-file"
        assert env["GH_TOKEN"] == "ghp_file"

    def test_env_file_overrides_os_environ(self, tmp_path):
        env_file = tmp_path / ".env.augint-shell"
        env_file.write_text("OPENAI_API_KEY=sk-from-file\n")
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-from-os"}):
            env = build_n8n_environment(env_file=env_file)
        assert env["OPENAI_API_KEY"] == "sk-from-file"


class TestBuildN8nMounts:
    def test_always_includes_data_volume(self, tmp_path):
        with patch("ai_shell.defaults.Path.home", return_value=tmp_path):
            mounts = build_n8n_mounts()
        targets = [m["Target"] for m in mounts]
        assert "/home/node/.n8n" in targets

    def test_data_volume_name(self, tmp_path):
        with patch("ai_shell.defaults.Path.home", return_value=tmp_path):
            mounts = build_n8n_mounts()
        data_mount = next(m for m in mounts if m["Target"] == "/home/node/.n8n")
        assert data_mount["Source"] == N8N_DATA_VOLUME

    def test_mounts_aws_when_exists(self, tmp_path):
        (tmp_path / ".aws").mkdir()
        with patch("ai_shell.defaults.Path.home", return_value=tmp_path):
            mounts = build_n8n_mounts()
        targets = [m["Target"] for m in mounts]
        assert "/home/node/.aws" in targets
        aws_mount = next(m for m in mounts if m["Target"] == "/home/node/.aws")
        assert aws_mount["ReadOnly"] is True

    def test_skips_aws_when_missing(self, tmp_path):
        with patch("ai_shell.defaults.Path.home", return_value=tmp_path):
            mounts = build_n8n_mounts()
        targets = [m["Target"] for m in mounts]
        assert "/home/node/.aws" not in targets

    def test_mounts_gh_config_when_exists(self, tmp_path):
        gh_dir = tmp_path / ".config" / "gh"
        gh_dir.mkdir(parents=True)
        with (
            patch("ai_shell.defaults.Path.home", return_value=tmp_path),
            patch.dict("os.environ", {}, clear=True),
        ):
            mounts = build_n8n_mounts()
        targets = [m["Target"] for m in mounts]
        assert "/home/node/.config/gh" in targets

    def test_mounts_workflow_dir(self, tmp_path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        with patch("ai_shell.defaults.Path.home", return_value=tmp_path):
            mounts = build_n8n_mounts(workflow_dir=wf_dir)
        targets = [m["Target"] for m in mounts]
        assert "/workflows" in targets
        wf_mount = next(m for m in mounts if m["Target"] == "/workflows")
        assert wf_mount["ReadOnly"] is True

    def test_skips_workflow_dir_when_missing(self, tmp_path):
        missing = tmp_path / "no-such-dir"
        with patch("ai_shell.defaults.Path.home", return_value=tmp_path):
            mounts = build_n8n_mounts(workflow_dir=missing)
        targets = [m["Target"] for m in mounts]
        assert "/workflows" not in targets
