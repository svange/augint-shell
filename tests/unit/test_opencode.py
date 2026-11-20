"""Unit tests for ai_shell.opencode module."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ai_shell.opencode import (
    BEDROCK_MANTLE_DEFAULT_PRIMARY_MODEL,
    BEDROCK_MANTLE_DEFAULT_SUBAGENT_MODEL,
    BEDROCK_MANTLE_OPENAI_PROVIDER_ID,
    BEDROCK_MANTLE_PROVIDER_ID,
    DEFAULT_OPENCODE_INSTRUCTIONS,
    DEFAULT_OPENCODE_PLUGINS,
    OPENCODE_NO_CLAUDE_ENV,
    CustomEndpoint,
    _generate_token_from_credentials,
    bedrock_mantle_base_url,
    bedrock_mantle_openai_base_url,
    bedrock_runtime_openai_base_url,
    build_opencode_config_patch,
    deep_merge_dict,
    generate_bedrock_bearer_token,
    mantle_provider_for_model,
    opencode_launch_env,
    opencode_local_mcp,
    parse_endpoint_spec,
    qualify_model_id,
    remove_skills_bridges,
    resolve_aws_partition,
    resolve_bedrock_bearer_token,
    resolve_bedrock_mantle_region,
    sanitize_provider_id,
    sync_opencode_config,
)


class TestSanitizeAndParseEndpoints:
    def test_sanitize_provider_id(self):
        assert sanitize_provider_id("My_VLLM Server!") == "my-vllm-server"
        assert sanitize_provider_id("---") == "custom"

    def test_parse_endpoint_spec_with_name_models_and_key(self):
        ep = parse_endpoint_spec(
            "vllm=http://gpu-box:8000/v1,model=Qwen/Qwen3-Coder-30B,model=fast-coder,api_key_env=VLLM_API_KEY"
        )
        assert ep.name == "vllm"
        assert ep.base_url == "http://gpu-box:8000/v1"
        assert ep.api_key_env == "VLLM_API_KEY"
        assert ep.models == ["Qwen/Qwen3-Coder-30B", "fast-coder"]

    def test_parse_endpoint_spec_bare_url(self):
        ep = parse_endpoint_spec(
            "https://llm.internal.gov/v1,key_env=GOV_LLM_KEY,display_name=GovLLM"
        )
        assert ep.name == "custom"
        assert ep.base_url == "https://llm.internal.gov/v1"
        assert ep.api_key_env == "GOV_LLM_KEY"
        assert ep.display_name == "GovLLM"

    def test_parse_endpoint_spec_models_pipe_delimited(self):
        ep = parse_endpoint_spec("sglang=http://localhost:30000/v1,models=model-a|model-b")
        assert ep.name == "sglang"
        assert ep.models == ["model-a", "model-b"]

    def test_parse_endpoint_spec_rejects_empty_or_invalid(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            parse_endpoint_spec("   ")
        with pytest.raises(ValueError, match="Invalid endpoint specification"):
            parse_endpoint_spec("not-a-url")
        with pytest.raises(ValueError, match="requires a non-empty base URL"):
            parse_endpoint_spec("vllm=")
        with pytest.raises(ValueError, match="Unsupported option"):
            parse_endpoint_spec("vllm=http://localhost:8000/v1,unknown=1")


class TestBedrockMantleUrlsAndRegions:
    def test_resolve_aws_partition(self):
        assert resolve_aws_partition(partition="govcloud") == "govcloud"
        assert resolve_aws_partition(partition="aws-us-gov") == "govcloud"
        assert resolve_aws_partition(partition="commercial") == "commercial"
        assert resolve_aws_partition(partition="aws") == "commercial"
        assert resolve_aws_partition(region="us-gov-west-1") == "govcloud"
        assert resolve_aws_partition(region="us-east-1") == "commercial"

    def test_resolve_aws_partition_invalid(self):
        with pytest.raises(ValueError, match="Unsupported AWS partition"):
            resolve_aws_partition(partition="aws-cn")

    def test_resolve_bedrock_mantle_region_defaults(self):
        assert resolve_bedrock_mantle_region(partition="commercial") == "us-east-1"
        assert resolve_bedrock_mantle_region(partition="govcloud") == "us-gov-west-1"
        assert resolve_bedrock_mantle_region() == "us-east-1"

    def test_resolve_bedrock_mantle_region_explicit(self):
        assert (
            resolve_bedrock_mantle_region(region="us-gov-east-1", partition="govcloud")
            == "us-gov-east-1"
        )
        assert (
            resolve_bedrock_mantle_region(region="us-west-2", partition="commercial") == "us-west-2"
        )

    def test_resolve_bedrock_mantle_region_rejects_mismatch(self):
        with pytest.raises(ValueError, match="not a GovCloud region"):
            resolve_bedrock_mantle_region(region="us-east-1", partition="govcloud")
        with pytest.raises(ValueError, match="GovCloud region"):
            resolve_bedrock_mantle_region(region="us-gov-west-1", partition="commercial")

    def test_bedrock_mantle_base_url_commercial_and_govcloud(self):
        assert (
            bedrock_mantle_base_url(partition="commercial")
            == "https://bedrock-mantle.us-east-1.api.aws/v1"
        )
        assert (
            bedrock_mantle_base_url(partition="govcloud")
            == "https://bedrock-mantle.us-gov-west-1.api.aws/v1"
        )
        assert (
            bedrock_mantle_openai_base_url(partition="govcloud")
            == "https://bedrock-mantle.us-gov-west-1.api.aws/openai/v1"
        )
        assert (
            bedrock_mantle_openai_base_url(region="us-gov-east-1")
            == "https://bedrock-mantle.us-gov-east-1.api.aws/openai/v1"
        )

    def test_mantle_provider_for_model_splits_gpt_and_gpt_oss(self):
        # Regression: GPT-5.x is served only on /openai/v1 and gpt-oss only on /v1.
        assert mantle_provider_for_model("openai.gpt-5.4") == BEDROCK_MANTLE_OPENAI_PROVIDER_ID
        assert (
            mantle_provider_for_model("openai.gpt-5.6-terra") == BEDROCK_MANTLE_OPENAI_PROVIDER_ID
        )
        assert mantle_provider_for_model("openai.gpt-oss-120b") == BEDROCK_MANTLE_PROVIDER_ID
        assert mantle_provider_for_model("openai.gpt-oss-20b") == BEDROCK_MANTLE_PROVIDER_ID
        assert mantle_provider_for_model("mistral.devstral-2-123b") == BEDROCK_MANTLE_PROVIDER_ID

    def test_grok_and_inference_profiles_go_to_bedrock_runtime(self):
        assert mantle_provider_for_model("xai.grok-4.7") == "bedrock-runtime"
        assert mantle_provider_for_model("us-gov.xai.grok-4.7") == "bedrock-runtime"
        assert mantle_provider_for_model("us.xai.grok-4.6") == "bedrock-runtime"
        assert mantle_provider_for_model("us-gov.openai.gpt-5.6-terra") == "bedrock-runtime"
        assert (
            bedrock_runtime_openai_base_url(region="us-gov-west-1")
            == "https://bedrock-runtime.us-gov-west-1.amazonaws.com/openai/v1"
        )


class TestBearerTokenGeneration:
    def test_generate_token_from_credentials_format(self):
        token = _generate_token_from_credentials(
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            session_token="AQoDYXdzEJr...",
            region="us-gov-west-1",
        )
        assert token.startswith("bedrock-api-key-")

    def test_stdlib_token_matches_aws_bedrock_token_generator(self):
        """Regression: the token must be what aws-bedrock-token-generator 1.1.0 makes.

        The old signer signed an extra ``Version=2023-09-30`` parameter, so the
        token did not match the AWS format. This test builds the reference token
        the way the AWS library does.
        """
        import base64
        import datetime

        botocore_auth = pytest.importorskip("botocore.auth")
        from botocore.awsrequest import AWSRequest
        from botocore.credentials import Credentials

        fixed = datetime.datetime(2026, 11, 17, 12, 0, 0, tzinfo=datetime.UTC)
        creds = Credentials("ASIAEXAMPLEKEY", "secretEXAMPLE", "session/token+EXAMPLE=")

        request = AWSRequest(
            method="POST",
            url="https://bedrock.amazonaws.com/",
            headers={"host": "bedrock.amazonaws.com"},
            params={"Action": "CallWithBearerToken"},
        )
        with patch.object(botocore_auth, "get_current_datetime", return_value=fixed):
            botocore_auth.SigV4QueryAuth(creds, "bedrock", "us-gov-west-1", expires=43200).add_auth(
                request
            )
        presigned = request.url.replace("https://", "") + "&Version=1"
        expected = "bedrock-api-key-" + base64.b64encode(presigned.encode()).decode()

        ours = _generate_token_from_credentials(
            access_key="ASIAEXAMPLEKEY",
            secret_key="secretEXAMPLE",
            session_token="session/token+EXAMPLE=",
            region="us-gov-west-1",
            now=fixed,
        )
        assert ours == expected

    def test_stdlib_token_rejects_expiry_over_12_hours(self):
        with pytest.raises(ValueError):
            _generate_token_from_credentials(
                access_key="AKIA", secret_key="s", region="us-gov-west-1", expires_in=43201
            )

    @patch("ai_shell.opencode._bedrock_credentials_via_botocore", return_value=None)
    @patch("ai_shell.opencode.subprocess.run")
    def test_in_container_generator_uses_profile_and_region(self, mock_run, _mock_botocore):
        # Regression: the old script passed Credentials where provide_token expects a
        # provider, so it always failed. It must call provide_token(region=...) only.
        mock_run.return_value = MagicMock(returncode=0, stdout="bedrock-api-key-abc\n", stderr="")
        token = generate_bedrock_bearer_token(
            profile="ai-gov", region="us-gov-west-1", container_name="augint-shell-x-dev"
        )
        assert token == "bedrock-api-key-abc"
        cmd = mock_run.call_args.args[0]
        assert cmd[:2] == ["docker", "exec"]
        assert "AWS_PROFILE=ai-gov" in cmd
        assert "AWS_REGION=us-gov-west-1" in cmd
        script = cmd[-1]
        assert "provide_token(region=" in script
        assert "aws_credentials_provider" not in script

    def test_resolve_bedrock_bearer_token_from_existing_env(self):
        env = {"AWS_BEARER_TOKEN_BEDROCK": "existing-token"}
        token = resolve_bedrock_bearer_token(env, generate_if_missing=False)
        assert token == "existing-token"
        assert env["AWS_BEARER_TOKEN_BEDROCK"] == "existing-token"
        assert env["BEDROCK_API_KEY"] == "existing-token"

    def test_resolve_bedrock_bearer_token_mirrors_bedrock_api_key(self):
        env = {"BEDROCK_API_KEY": "from-bedrock-api-key"}
        token = resolve_bedrock_bearer_token(env, generate_if_missing=False)
        assert token == "from-bedrock-api-key"
        assert env["AWS_BEARER_TOKEN_BEDROCK"] == "from-bedrock-api-key"

    def test_resolve_bedrock_bearer_token_generates_when_missing(self):
        env: dict[str, str] = {}
        with patch(
            "ai_shell.opencode.generate_bedrock_bearer_token",
            return_value="generated-short-term-token",
        ) as mock_gen:
            token = resolve_bedrock_bearer_token(
                env,
                profile="gov-sso",
                region="us-gov-west-1",
                container_name="augint-shell-demo-dev",
                generate_if_missing=True,
            )
        assert token == "generated-short-term-token"
        assert env["AWS_BEARER_TOKEN_BEDROCK"] == "generated-short-term-token"
        assert env["BEDROCK_API_KEY"] == "generated-short-term-token"
        mock_gen.assert_called_once_with(
            profile="gov-sso",
            region="us-gov-west-1",
            container_name="augint-shell-demo-dev",
        )

    @patch("ai_shell.opencode._bedrock_credentials_via_botocore", return_value=None)
    @patch("ai_shell.opencode.subprocess.run")
    def test_generate_bedrock_bearer_token_falls_back_to_aws_cli(self, mock_run, _mock_botocore):
        creds_json = json.dumps(
            {
                "AccessKeyId": "ASIATESTKEY",
                "SecretAccessKey": "testsecret",
                "SessionToken": "testsession",
            }
        )
        mock_run.return_value = MagicMock(returncode=0, stdout=creds_json, stderr="")
        token = generate_bedrock_bearer_token(profile="gov-sso", region="us-gov-west-1")
        assert token is not None
        assert token.startswith("bedrock-api-key-")


class TestQualifyModelAndConfigMerging:
    def test_qualify_model_id_handles_known_and_hf_slash_models(self):
        known = {"bedrock-mantle", "vllm"}
        # Unqualified model gets default provider prefix
        assert (
            qualify_model_id("openai.gpt-5.4", "bedrock-mantle", known)
            == "bedrock-mantle/openai.gpt-5.4"
        )
        # Already qualified with known provider stays untouched
        assert (
            qualify_model_id("vllm/Qwen/Qwen3-Coder-30B", "bedrock-mantle", known)
            == "vllm/Qwen/Qwen3-Coder-30B"
        )
        # HuggingFace ID with slash (Org/Model) where Org is not a provider gets prefixed
        assert (
            qualify_model_id("Qwen/Qwen3-Coder-30B", "vllm", known) == "vllm/Qwen/Qwen3-Coder-30B"
        )

    def test_build_opencode_config_patch_bedrock_and_custom_split(self):
        vllm_ep = CustomEndpoint(
            name="vllm",
            base_url="http://gpu-box:8000/v1",
            api_key_env="VLLM_API_KEY",
            models=["Qwen/Qwen3-Coder-30B-A3B-Instruct"],
        )
        patch_dict = build_opencode_config_patch(
            bedrock_region="us-gov-west-1",
            custom_endpoints=[vllm_ep],
            primary_model="openai.gpt-5.4",
            subagent_model="vllm/Qwen/Qwen3-Coder-30B-A3B-Instruct",
        )
        assert (
            patch_dict["provider"][BEDROCK_MANTLE_PROVIDER_ID]["options"]["baseURL"]
            == "https://bedrock-mantle.us-gov-west-1.api.aws/v1"
        )
        assert (
            patch_dict["provider"][BEDROCK_MANTLE_OPENAI_PROVIDER_ID]["options"]["baseURL"]
            == "https://bedrock-mantle.us-gov-west-1.api.aws/openai/v1"
        )
        assert (
            patch_dict["provider"][BEDROCK_MANTLE_OPENAI_PROVIDER_ID]["options"]["apiKey"]
            == "{env:AWS_BEARER_TOKEN_BEDROCK}"
        )
        assert (
            patch_dict["provider"][BEDROCK_MANTLE_PROVIDER_ID]["options"]["apiKey"]
            == "{env:AWS_BEARER_TOKEN_BEDROCK}"
        )
        assert patch_dict["provider"]["vllm"]["options"]["baseURL"] == "http://gpu-box:8000/v1"
        assert patch_dict["provider"]["vllm"]["options"]["apiKey"] == "{env:VLLM_API_KEY}"
        assert "Qwen/Qwen3-Coder-30B-A3B-Instruct" in patch_dict["provider"]["vllm"]["models"]
        # Primary vs subagent routing
        assert patch_dict["model"] == f"{BEDROCK_MANTLE_OPENAI_PROVIDER_ID}/openai.gpt-5.4"
        assert patch_dict["small_model"] == "vllm/Qwen/Qwen3-Coder-30B-A3B-Instruct"
        assert (
            patch_dict["agent"]["plan"]["model"]
            == f"{BEDROCK_MANTLE_OPENAI_PROVIDER_ID}/openai.gpt-5.4"
        )
        assert (
            patch_dict["agent"]["build"]["model"]
            == f"{BEDROCK_MANTLE_OPENAI_PROVIDER_ID}/openai.gpt-5.4"
        )
        assert patch_dict["agent"]["explore"]["model"] == "vllm/Qwen/Qwen3-Coder-30B-A3B-Instruct"
        assert patch_dict["agent"]["general"]["model"] == "vllm/Qwen/Qwen3-Coder-30B-A3B-Instruct"

    def test_sync_opencode_config_preserves_unrelated_user_settings(self, tmp_path: Path):
        config_path = tmp_path / "opencode.json"
        existing = {
            "$schema": "https://opencode.ai/config.json",
            "theme": "catppuccin",
            "keybinds": {"leader": "ctrl+x"},
            "mcp": {"my-server": {"type": "local", "command": ["npx", "my-mcp"]}},
            "provider": {
                "existing-provider": {
                    "npm": "@ai-sdk/openai-compatible",
                    "options": {"baseURL": "http://localhost:1234/v1"},
                }
            },
            "agent": {
                "plan": {"prompt": "Always think step by step."},
                "custom-agent": {"model": "existing-provider/foo"},
            },
        }
        config_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

        merged = sync_opencode_config(
            config_path=config_path,
            bedrock_region="us-east-1",
        )

        # User settings are untouched
        assert merged["theme"] == "catppuccin"
        assert merged["keybinds"] == {"leader": "ctrl+x"}
        assert "my-server" in merged["mcp"]
        assert "existing-provider" in merged["provider"]
        assert merged["agent"]["plan"]["prompt"] == "Always think step by step."
        assert merged["agent"]["custom-agent"]["model"] == "existing-provider/foo"

        # Default Bedrock Mantle models applied
        assert (
            merged["agent"]["plan"]["model"]
            == f"{BEDROCK_MANTLE_OPENAI_PROVIDER_ID}/{BEDROCK_MANTLE_DEFAULT_PRIMARY_MODEL}"
        )
        assert (
            merged["agent"]["build"]["model"]
            == f"{BEDROCK_MANTLE_OPENAI_PROVIDER_ID}/{BEDROCK_MANTLE_DEFAULT_PRIMARY_MODEL}"
        )
        assert (
            merged["agent"]["explore"]["model"]
            == f"{BEDROCK_MANTLE_OPENAI_PROVIDER_ID}/{BEDROCK_MANTLE_DEFAULT_SUBAGENT_MODEL}"
        )
        assert (
            merged["agent"]["general"]["model"]
            == f"{BEDROCK_MANTLE_OPENAI_PROVIDER_ID}/{BEDROCK_MANTLE_DEFAULT_SUBAGENT_MODEL}"
        )

        # File on disk matches merged dict
        on_disk = json.loads(config_path.read_text(encoding="utf-8"))
        assert on_disk == merged

    def test_explicit_bedrock_mantle_gpt_model_is_rerouted(self):
        # Regression: "bedrock-mantle/openai.gpt-5.4" (the old documented form) must
        # land on the /openai/v1 provider, or Mantle rejects it.
        patch_dict = build_opencode_config_patch(
            bedrock_region="us-gov-west-1",
            primary_model="bedrock-mantle/openai.gpt-5.4",
            subagent_model="bedrock-mantle/openai.gpt-oss-120b",
        )
        assert patch_dict["model"] == "bedrock-mantle-openai/openai.gpt-5.4"
        assert patch_dict["small_model"] == "bedrock-mantle/openai.gpt-oss-120b"
        assert "openai.gpt-5.4" not in patch_dict["provider"]["bedrock-mantle"]["models"]
        assert "openai.gpt-oss-120b" in patch_dict["provider"]["bedrock-mantle"]["models"]
        assert "openai.gpt-5.4" in patch_dict["provider"]["bedrock-mantle-openai"]["models"]

    def test_commercial_defaults_are_terra_and_luna(self):
        patch_dict = build_opencode_config_patch(bedrock_region="us-east-1")
        assert patch_dict["model"] == "bedrock-mantle-openai/openai.gpt-5.6-terra"
        assert patch_dict["small_model"] == "bedrock-mantle-openai/openai.gpt-5.6-luna"
        assert (
            patch_dict["agent"]["explore"]["model"] == "bedrock-mantle-openai/openai.gpt-5.6-luna"
        )
        assert "disabled_providers" not in patch_dict

    def test_govcloud_defaults_are_gpt_oss_120b(self):
        # Regression: GovCloud refused Terra and Luna ("not available for this account").
        patch_dict = build_opencode_config_patch(bedrock_region="us-gov-west-1")
        assert patch_dict["model"] == "bedrock-mantle/openai.gpt-oss-120b"
        assert patch_dict["small_model"] == "bedrock-mantle/openai.gpt-oss-120b"
        assert patch_dict["agent"]["build"]["model"] == "bedrock-mantle/openai.gpt-oss-120b"
        assert patch_dict["agent"]["general"]["model"] == "bedrock-mantle/openai.gpt-oss-120b"

    def test_govcloud_partition_alone_picks_govcloud_defaults(self):
        patch_dict = build_opencode_config_patch(use_bedrock_mantle=True, aws_partition="govcloud")
        assert patch_dict["model"] == "bedrock-mantle/openai.gpt-oss-120b"

    def test_govcloud_turns_off_the_builtin_providers(self):
        # Regression: on the box OpenCode offered amazon-bedrock (Anthropic models) and
        # its own hosted "opencode" provider, which is outside GovCloud.
        patch_dict = build_opencode_config_patch(bedrock_region="us-gov-west-1")
        assert patch_dict["disabled_providers"] == ["amazon-bedrock", "opencode"]
        assert patch_dict["enabled_providers"] == [
            "bedrock-mantle",
            "bedrock-mantle-openai",
            "bedrock-runtime",
        ]

    def test_govcloud_allows_configured_endpoints(self):
        patch_dict = build_opencode_config_patch(
            bedrock_region="us-gov-west-1",
            custom_endpoints=[
                CustomEndpoint(name="govcloud-gpu", base_url="http://x:8000/v1", models=["m"])
            ],
        )
        assert "govcloud-gpu" in patch_dict["enabled_providers"]
        assert "opencode" not in patch_dict["enabled_providers"]

    def test_commercial_sets_no_provider_lists(self):
        patch_dict = build_opencode_config_patch(bedrock_region="us-east-1")
        assert "enabled_providers" not in patch_dict

    def test_every_bedrock_model_has_a_limit(self):
        # Regression: limit {context: 0, output: 0} made OpenCode read a quota error
        # as a context overflow.
        patch_dict = build_opencode_config_patch(
            bedrock_region="us-gov-west-1", primary_model="xai.grok-4.7"
        )
        for provider in ("bedrock-mantle", "bedrock-mantle-openai", "bedrock-runtime"):
            for model_id, entry in patch_dict["provider"][provider]["models"].items():
                assert entry["limit"]["context"] > 0, model_id
                assert entry["limit"]["output"] > 0, model_id
        mantle = patch_dict["provider"]["bedrock-mantle"]["models"]
        assert mantle["openai.gpt-oss-120b"]["limit"] == {"context": 128000, "output": 16384}
        runtime = patch_dict["provider"]["bedrock-runtime"]["models"]
        assert runtime["us-gov.xai.grok-4.7"]["limit"]["context"] == 500000

    def test_sync_keeps_the_users_disabled_providers(self, tmp_path: Path):
        config_path = tmp_path / "opencode.json"
        config_path.write_text(json.dumps({"disabled_providers": ["openrouter"]}))
        merged = sync_opencode_config(config_path=config_path, bedrock_region="us-gov-west-1")
        assert merged["disabled_providers"] == ["openrouter", "amazon-bedrock", "opencode"]

    def test_grok_gets_govcloud_inference_profile_on_bedrock_runtime(self):
        patch_dict = build_opencode_config_patch(
            bedrock_region="us-gov-west-1", primary_model="xai.grok-4.7"
        )
        assert patch_dict["model"] == "bedrock-runtime/us-gov.xai.grok-4.7"
        runtime = patch_dict["provider"]["bedrock-runtime"]
        assert (
            runtime["options"]["baseURL"]
            == "https://bedrock-runtime.us-gov-west-1.amazonaws.com/openai/v1"
        )
        assert runtime["options"]["apiKey"] == "{env:AWS_BEARER_TOKEN_BEDROCK}"
        assert set(runtime["models"]) == {"us-gov.xai.grok-4.7", "us-gov.xai.grok-4.6"}

    def test_grok_uses_us_profile_in_commercial_regions(self):
        patch_dict = build_opencode_config_patch(
            bedrock_region="us-east-1", subagent_model="bedrock-mantle/xai.grok-4.6"
        )
        assert patch_dict["small_model"] == "bedrock-runtime/us.xai.grok-4.6"
        assert "us.xai.grok-4.7" in patch_dict["provider"]["bedrock-runtime"]["models"]

    def test_sync_removes_gpt_models_left_on_v1_route_by_older_versions(self, tmp_path: Path):
        config_path = tmp_path / "opencode.json"
        old = {
            "provider": {
                "bedrock-mantle": {
                    "npm": "@ai-sdk/openai-compatible",
                    "options": {
                        "baseURL": "https://bedrock-mantle.us-gov-west-1.api.aws/openai/v1"
                    },
                    "models": {
                        "openai.gpt-5.4": {"name": "openai.gpt-5.4"},
                        "openai.gpt-oss-120b": {"name": "openai.gpt-oss-120b"},
                        "my-extra-model": {"name": "kept"},
                    },
                }
            }
        }
        config_path.write_text(json.dumps(old), encoding="utf-8")
        merged = sync_opencode_config(config_path=config_path, bedrock_region="us-gov-west-1")
        mantle = merged["provider"]["bedrock-mantle"]
        assert mantle["options"]["baseURL"] == "https://bedrock-mantle.us-gov-west-1.api.aws/v1"
        assert "openai.gpt-5.4" not in mantle["models"]
        assert "my-extra-model" in mantle["models"]
        assert "openai.gpt-5.4" in merged["provider"]["bedrock-mantle-openai"]["models"]

    def test_deep_merge_dict_does_not_mutate_base(self):
        base = {"a": {"x": 1}, "b": 2}
        patch_d = {"a": {"y": 3}}
        merged = deep_merge_dict(base, patch_d)
        assert merged == {"a": {"x": 1, "y": 3}, "b": 2}
        assert base == {"a": {"x": 1}, "b": 2}


class TestRemoveSkillsBridges:
    """Regression: the old bridge loaded Claude Code skills even with compat off."""

    def test_removes_global_link_to_claude_skills(self, tmp_path: Path):
        home = tmp_path / "home"
        (home / ".claude" / "skills" / "org-rule").mkdir(parents=True)
        (home / ".config" / "opencode").mkdir(parents=True)
        link = home / ".config" / "opencode" / "skills"
        link.symlink_to(home / ".claude" / "skills", target_is_directory=True)

        assert remove_skills_bridges(home_dir=home) == [link]
        assert not link.is_symlink()
        assert (home / ".claude" / "skills" / "org-rule").is_dir()

    def test_removes_global_link_to_agents_skills_made_in_container(self, tmp_path: Path):
        home = tmp_path / "home"
        (home / ".config" / "opencode").mkdir(parents=True)
        link = home / ".config" / "opencode" / "skills"
        link.symlink_to("/root/.agents/skills", target_is_directory=True)

        assert remove_skills_bridges(home_dir=home) == [link]
        assert not link.is_symlink()

    def test_removes_project_link(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        project = tmp_path / "repo"
        (project / ".agents" / "skills").mkdir(parents=True)
        (project / ".opencode").mkdir()
        link = project / ".opencode" / "skills"
        link.symlink_to(Path("..") / ".agents" / "skills", target_is_directory=True)

        assert remove_skills_bridges(project_dir=project, home_dir=home) == [link]
        assert not link.is_symlink()
        assert (project / ".agents" / "skills").is_dir()

    def test_keeps_real_skills_dir_and_other_links(self, tmp_path: Path):
        home = tmp_path / "home"
        own = home / ".config" / "opencode" / "skills"
        own.mkdir(parents=True)
        project = tmp_path / "repo"
        (project / "my-skills").mkdir(parents=True)
        (project / ".opencode").mkdir()
        other = project / ".opencode" / "skills"
        other.symlink_to(Path("..") / "my-skills", target_is_directory=True)

        assert remove_skills_bridges(project_dir=project, home_dir=home) == []
        assert own.is_dir()
        assert other.is_symlink()

    def test_creates_nothing(self, tmp_path: Path):
        home = tmp_path / "home"
        project = tmp_path / "repo"
        project.mkdir()

        assert remove_skills_bridges(project_dir=project, home_dir=home) == []
        assert not home.exists()
        assert list(project.iterdir()) == []


class TestOpencodeLaunchEnv:
    def test_claude_compat_off_by_default(self):
        env = opencode_launch_env()
        assert env == OPENCODE_NO_CLAUDE_ENV
        assert env["OPENCODE_DISABLE_CLAUDE_CODE"] == "1"
        assert env["OPENCODE_DISABLE_EXTERNAL_SKILLS"] == "1"

    def test_claude_compat_sets_no_flags(self):
        assert opencode_launch_env(claude_compat=True) == {}

    def test_plugins_instructions_and_mcp_go_in_config_content(self):
        mcp = {"chrome-devtools": opencode_local_mcp("chrome-devtools-mcp", ["--browserUrl", "u"])}
        env = opencode_launch_env(
            plugins=DEFAULT_OPENCODE_PLUGINS,
            instructions=DEFAULT_OPENCODE_INSTRUCTIONS,
            mcp=mcp,
        )
        content = json.loads(env["OPENCODE_CONFIG_CONTENT"])
        assert content["plugin"] == list(DEFAULT_OPENCODE_PLUGINS)
        assert content["instructions"] == list(DEFAULT_OPENCODE_INSTRUCTIONS)
        assert content["mcp"]["chrome-devtools"] == {
            "type": "local",
            "command": ["chrome-devtools-mcp", "--browserUrl", "u"],
            "enabled": True,
        }

    def test_empty_lists_write_no_config_content(self):
        assert "OPENCODE_CONFIG_CONTENT" not in opencode_launch_env(plugins=[], instructions=[])

    def test_defaults_are_pinned(self):
        assert all("@" in p.lstrip("@") for p in DEFAULT_OPENCODE_PLUGINS)
        assert all("/trunk/" not in u and "/main/" not in u for u in DEFAULT_OPENCODE_INSTRUCTIONS)


class TestOpencodeServerPassword:
    def test_made_once_and_kept(self, tmp_path):
        from ai_shell.opencode import opencode_server_password, opencode_server_password_path

        first = opencode_server_password(tmp_path)
        assert opencode_server_password(tmp_path) == first
        path = opencode_server_password_path(tmp_path)
        assert path.read_text().strip() == first
        if os.name == "posix":
            assert path.stat().st_mode & 0o777 == 0o600

    def test_saved_value_wins(self, tmp_path):
        from ai_shell.opencode import opencode_server_password, opencode_server_password_path

        path = opencode_server_password_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("my-own-password\n")
        assert opencode_server_password(tmp_path) == "my-own-password"


class TestOpencodeSignInUrl:
    def test_token_is_base64_user_and_password(self):
        import base64
        from urllib.parse import parse_qs, urlparse

        from ai_shell.opencode import opencode_sign_in_url

        url = opencode_sign_in_url("http://localhost:32877", "p+w/d=", "opencode")
        parsed = urlparse(url)
        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "http://localhost:32877/"
        token = parse_qs(parsed.query)["auth_token"][0]
        assert base64.b64decode(token) == b"opencode:p+w/d="

    def test_no_password_keeps_the_plain_url(self):
        from ai_shell.opencode import opencode_sign_in_url

        assert opencode_sign_in_url("http://localhost:4096", "") == "http://localhost:4096"

    def test_trailing_slash_is_not_doubled(self):
        from ai_shell.opencode import opencode_sign_in_url

        assert opencode_sign_in_url("http://localhost:4096/", "x").startswith(
            "http://localhost:4096/?auth_token="
        )
