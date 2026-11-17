"""OpenCode configuration, Bedrock Mantle endpoints, and multi-model routing.

Manages dynamic generation and non-destructive deep-merging of
``~/.config/opencode/opencode.json`` for:
1. AWS Bedrock Mantle OpenAI-compatible endpoints (Commercial & GovCloud).
2. Custom OpenAI-compatible endpoints (self-hosted vLLM, SGLang, etc.).
3. Primary agent (``plan``, ``build``) and subagent (``explore``, ``general``)
   model routing.
4. The launch environment: Claude Code compatibility off, plugins, instructions
   and MCP servers passed in ``OPENCODE_CONFIG_CONTENT`` (no file is written).
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

logger = logging.getLogger(__name__)

OPENCODE_SCHEMA_URL = "https://opencode.ai/config.json"
BEDROCK_MANTLE_PROVIDER_ID = "bedrock-mantle"
BEDROCK_MANTLE_OPENAI_PROVIDER_ID = "bedrock-mantle-openai"
BEDROCK_RUNTIME_PROVIDER_ID = "bedrock-runtime"
MANTLE_PROVIDER_IDS: tuple[str, ...] = (
    BEDROCK_MANTLE_PROVIDER_ID,
    BEDROCK_MANTLE_OPENAI_PROVIDER_ID,
    BEDROCK_RUNTIME_PROVIDER_ID,
)
# Cross-Region inference profile prefixes (``us.``, ``us-gov.``, ``global.``).
# A model ID with one of these is served by bedrock-runtime, not bedrock-mantle.
_INFERENCE_PROFILE_PREFIX = re.compile(r"^(us-gov|us|global|eu|apac|jp|au|ca)\.", re.IGNORECASE)
OPENAI_COMPATIBLE_NPM = "@ai-sdk/openai-compatible"

DEFAULT_COMMERCIAL_REGION = "us-east-1"
DEFAULT_GOVCLOUD_REGION = "us-gov-west-1"

DEFAULT_BEDROCK_MANTLE_PRIMARY_MODEL = "openai.gpt-5.6-terra"
DEFAULT_BEDROCK_MANTLE_SUBAGENT_MODEL = "openai.gpt-5.6-luna"
BEDROCK_MANTLE_DEFAULT_PRIMARY_MODEL = DEFAULT_BEDROCK_MANTLE_PRIMARY_MODEL
BEDROCK_MANTLE_DEFAULT_SUBAGENT_MODEL = DEFAULT_BEDROCK_MANTLE_SUBAGENT_MODEL
# Models listed in the OpenCode model picker. Mantle serves gpt-oss on /v1 and
# GPT-5.x on /openai/v1, and Grok is served by bedrock-runtime, so each list
# becomes its own provider.
BEDROCK_MANTLE_DEFAULT_MODELS: tuple[str, ...] = (
    "openai.gpt-oss-120b",
    "openai.gpt-oss-20b",
)
BEDROCK_MANTLE_OPENAI_DEFAULT_MODELS: tuple[str, ...] = (
    "openai.gpt-5.6-terra",
    "openai.gpt-5.6-luna",
    "openai.gpt-5.4",
)
# Base IDs; the Region's inference profile prefix (us. or us-gov.) is added.
BEDROCK_RUNTIME_DEFAULT_BASE_MODELS: tuple[str, ...] = (
    "xai.grok-4.7",
    "xai.grok-4.6",
)

PRIMARY_AGENTS: tuple[str, ...] = ("plan", "build")
SUBAGENTS: tuple[str, ...] = ("explore", "general")

BEDROCK_BEARER_TOKEN_VAR = "AWS_BEARER_TOKEN_BEDROCK"
BEDROCK_API_KEY_VAR = "BEDROCK_API_KEY"
BEDROCK_TOKEN_HOST = "bedrock.amazonaws.com"
BEDROCK_TOKEN_PREFIX = "bedrock-api-key-"
BEDROCK_TOKEN_MAX_SECONDS = 43200  # 12 hours, the most AWS allows

# OpenCode reads Claude Code files unless told not to: ~/.claude/CLAUDE.md,
# a project CLAUDE.md, and skills in ~/.claude/skills, ~/.agents/skills and the
# project's .claude/ and .agents/ directories. These flags turn all of that
# off, so only AGENTS.md and OpenCode's own config directories are read.
# ``opencode.claude_compat: true`` leaves them unset.
OPENCODE_NO_CLAUDE_ENV: dict[str, str] = {
    "OPENCODE_DISABLE_CLAUDE_CODE": "1",
    "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
}

# Plugins and instruction files every launch gets unless ``opencode.plugins``
# or ``opencode.instructions`` is set (``[]`` turns them off). Pinned, so a new
# upstream release changes nothing until it is bumped here.
PLANNOTATOR_PLUGIN = "@plannotator/opencode@0.28.67"
OPENCODE_PTY_PLUGIN = "opencode-pty@0.4.0"
DEFAULT_OPENCODE_PLUGINS: tuple[str, ...] = (PLANNOTATOR_PLUGIN, OPENCODE_PTY_PLUGIN)
# opencode-shell-strategy is an instruction file, not a plugin. The URL names a
# commit, so the text cannot change under us.
SHELL_STRATEGY_INSTRUCTIONS_URL = (
    "https://raw.githubusercontent.com/JRedeker/opencode-shell-strategy/"
    "1303f24df1649202834e052f1d66560ed186e413/shell_strategy.md"
)
DEFAULT_OPENCODE_INSTRUCTIONS: tuple[str, ...] = (SHELL_STRATEGY_INSTRUCTIONS_URL,)
PLANNOTATOR_CONTAINER_PORT = 19432  # PLANNOTATOR_PORT in build_dev_environment

_BUILTIN_PROVIDERS = frozenset(
    {
        BEDROCK_MANTLE_PROVIDER_ID,
        BEDROCK_MANTLE_OPENAI_PROVIDER_ID,
        "ollama",
        "openai",
        "anthropic",
        "amazon-bedrock",
        "google",
        "azure",
        "openrouter",
    }
)


@dataclass
class CustomEndpoint:
    """A custom OpenAI-compatible provider endpoint for OpenCode."""

    name: str
    base_url: str
    api_key_env: str = ""
    models: list[str] = field(default_factory=list)
    display_name: str = ""


def sanitize_provider_id(name: str) -> str:
    """Normalize a custom endpoint name into a clean OpenCode provider ID."""
    cleaned = re.sub(r"[^a-zA-Z0-9-]+", "-", name.strip()).strip("-")
    return cleaned.lower() or "custom"


def parse_endpoint_spec(spec: str, default_index: int = 1) -> CustomEndpoint:
    """Parse a CLI ``--endpoint`` specification into a :class:`CustomEndpoint`.

    Accepted formats:
    - ``https://vllm.internal/v1`` (auto-named ``custom`` or ``custom-N``)
    - ``vllm=http://host.docker.internal:8000/v1``
    - ``vllm=http://host.docker.internal:8000/v1,model=Qwen/Qwen2.5-Coder-32B,api_key_env=VLLM_API_KEY``
    - ``url=http://...,name=vllm,model=...,key_env=...``
    """
    raw = spec.strip()
    if not raw:
        raise ValueError("Endpoint specification cannot be empty")

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    first = parts[0]

    name = "custom" if default_index == 1 else f"custom-{default_index}"
    base_url = ""
    api_key_env = ""
    display_name = ""
    models: list[str] = []

    if "://" in first:
        eq_pos = first.find("=")
        scheme_pos = first.find("://")
        if eq_pos != -1 and eq_pos < scheme_pos:
            lhs, rhs = first.split("=", 1)
            if lhs.strip().lower() in ("url", "base_url", "baseurl"):
                base_url = rhs.strip()
            else:
                name = sanitize_provider_id(lhs)
                base_url = rhs.strip()
        else:
            base_url = first
    elif "=" in first:
        lhs, rhs = first.split("=", 1)
        if not rhs.strip():
            raise ValueError(f"Endpoint '{lhs.strip()}' requires a non-empty base URL")
        raise ValueError(
            f"Invalid endpoint specification '{spec}': base URL must start with http:// or https://"
        )
    else:
        raise ValueError(
            f"Invalid endpoint specification '{spec}': first segment must contain a URL "
            "(e.g. 'vllm=http://host.docker.internal:8000/v1')"
        )

    for item in parts[1:]:
        if "=" not in item:
            raise ValueError(
                f"Invalid --endpoint option '{item}' in '{spec}': expected key=value "
                "(supported keys: name, model, api_key_env, display_name)"
            )
        k, v = (s.strip() for s in item.split("=", 1))
        key_lower = k.lower()
        if key_lower in ("name", "id", "provider"):
            name = sanitize_provider_id(v)
        elif key_lower in ("display_name", "title", "label"):
            display_name = v
        elif key_lower in ("model", "models"):
            for m in re.split(r"[;|]", v):
                if m.strip() and m.strip() not in models:
                    models.append(m.strip())
        elif key_lower in ("api_key_env", "key_env", "env", "api_key"):
            api_key_env = v
        else:
            raise ValueError(
                f"Unsupported option '{k}' in '{spec}' (supported: name, model, api_key_env, display_name)"
            )

    if not base_url:
        raise ValueError(f"Endpoint '{name}' requires a non-empty base URL")

    return CustomEndpoint(
        name=name,
        base_url=base_url.rstrip("/"),
        api_key_env=api_key_env,
        models=models,
        display_name=display_name,
    )


def resolve_aws_partition(partition: str = "", region: str = "") -> str:
    """Resolve the AWS partition to ``'commercial'`` or ``'govcloud'``.

    When *partition* is omitted, infers ``'govcloud'`` when *region* starts
    with ``us-gov-`` and ``'commercial'`` otherwise.
    """
    norm = partition.strip().lower()
    if norm in ("", "auto"):
        if region.strip().lower().startswith("us-gov-"):
            return "govcloud"
        return "commercial"
    if norm in ("commercial", "aws", "standard"):
        return "commercial"
    if norm in ("govcloud", "aws-us-gov", "gov", "us-gov"):
        return "govcloud"
    raise ValueError(
        f"Unsupported AWS partition '{partition}': expected 'commercial' or 'govcloud'"
    )


def resolve_bedrock_mantle_region(region: str = "", partition: str = "") -> str:
    """Resolve the AWS region for Bedrock Mantle endpoints.

    Defaults cleanly to ``us-gov-west-1`` for ``govcloud`` and ``us-east-1``
    for ``commercial``. Validates that an explicit region matches the
    requested partition.
    """
    clean_region = region.strip().lower()
    resolved_partition = resolve_aws_partition(partition, clean_region)

    if clean_region:
        if resolved_partition == "govcloud" and not clean_region.startswith("us-gov-"):
            raise ValueError(
                f"Region '{clean_region}' is not a GovCloud region (expected 'us-gov-*')"
            )
        if resolved_partition == "commercial" and clean_region.startswith("us-gov-"):
            raise ValueError(
                f"AWS partition 'commercial' cannot use GovCloud region '{clean_region}'"
            )
        return clean_region

    if resolved_partition == "govcloud":
        return DEFAULT_GOVCLOUD_REGION
    return DEFAULT_COMMERCIAL_REGION


def bedrock_mantle_base_url(region: str = "", partition: str = "") -> str:
    """Construct the Bedrock Mantle base URL for most models (``/v1`` route).

    Returns ``https://bedrock-mantle.<region>.api.aws/v1``. gpt-oss and most
    other models are served here.
    """
    resolved_region = resolve_bedrock_mantle_region(region=region, partition=partition)
    return f"https://bedrock-mantle.{resolved_region}.api.aws/v1"


def bedrock_mantle_openai_base_url(region: str = "", partition: str = "") -> str:
    """Construct the Bedrock Mantle base URL for OpenAI GPT models (``/openai/v1`` route).

    Returns ``https://bedrock-mantle.<region>.api.aws/openai/v1``. AWS serves
    GPT-5.x on this route only; a request on the wrong route is rejected with
    "model isn't supported on this route".
    """
    resolved_region = resolve_bedrock_mantle_region(region=region, partition=partition)
    return f"https://bedrock-mantle.{resolved_region}.api.aws/openai/v1"


def bedrock_runtime_openai_base_url(region: str = "", partition: str = "") -> str:
    """Construct the bedrock-runtime OpenAI-compatible base URL.

    Returns ``https://bedrock-runtime.<region>.amazonaws.com/openai/v1``.
    Grok 4.7 is served only here, through a cross-Region inference profile.
    """
    resolved_region = resolve_bedrock_mantle_region(region=region, partition=partition)
    return f"https://bedrock-runtime.{resolved_region}.amazonaws.com/openai/v1"


def inference_profile_prefix(region: str) -> str:
    """Return the geo inference profile prefix for *region*: ``us-gov`` or ``us``."""
    return "us-gov" if region.strip().lower().startswith("us-gov-") else "us"


def is_mantle_openai_route_model(model_id: str) -> bool:
    """Return True when Bedrock Mantle serves *model_id* on the ``/openai/v1`` route.

    OpenAI GPT models (``openai.gpt-5.4``, ``openai.gpt-5.6-*``) use
    ``/openai/v1``. The open-weight ``openai.gpt-oss-*`` models and the other
    providers' models use ``/v1``.
    """
    bare = model_id.strip().lower()
    return bare.startswith("openai.") and not bare.startswith("openai.gpt-oss")


def is_bedrock_runtime_model(model_id: str) -> bool:
    """Return True when ai-shell sends *model_id* to bedrock-runtime.

    That is any inference profile ID (``us.``, ``us-gov.``, ``global.`` ...)
    and any xAI Grok model. Grok 4.7 is not on bedrock-mantle at all, and
    Grok 4.6 is on bedrock-mantle in us-gov-east-1 but not us-gov-west-1.
    """
    bare = model_id.strip().lower()
    return bool(_INFERENCE_PROFILE_PREFIX.match(bare)) or bare.startswith("xai.")


def mantle_provider_for_model(model_id: str) -> str:
    """Return the OpenCode provider ID that serves the Bedrock model *model_id*."""
    if is_bedrock_runtime_model(model_id):
        return BEDROCK_RUNTIME_PROVIDER_ID
    if is_mantle_openai_route_model(model_id):
        return BEDROCK_MANTLE_OPENAI_PROVIDER_ID
    return BEDROCK_MANTLE_PROVIDER_ID


def with_inference_profile(model_id: str, region: str) -> str:
    """Add the Region's geo prefix to a bare bedrock-runtime model ID."""
    clean = model_id.strip()
    if _INFERENCE_PROFILE_PREFIX.match(clean):
        return clean
    return f"{inference_profile_prefix(region)}.{clean}"


def _bedrock_credentials_via_botocore(profile: str = "") -> tuple[str, str, str] | None:
    """Return ``(access_key, secret_key, session_token)`` from botocore, if it is installed."""
    try:
        import botocore.session  # type: ignore[import-not-found,import-untyped]
    except ImportError:
        return None
    try:
        session = botocore.session.Session(profile=profile or None)
        creds = session.get_credentials()
        if creds is None:
            return None
        frozen = creds.get_frozen_credentials()
    except Exception:  # noqa: BLE001 - any botocore failure means "no host credentials"
        logger.debug("botocore could not load credentials for profile %r", profile)
        return None
    if not frozen.access_key or not frozen.secret_key:
        return None
    return frozen.access_key, frozen.secret_key, frozen.token or ""


def _bedrock_credentials_via_aws_cli(profile: str = "") -> tuple[str, str, str] | None:
    """Return credentials from ``aws configure export-credentials`` on the host."""
    aws_cmd = ["aws", "configure", "export-credentials", "--format", "process"]
    if profile:
        aws_cmd.extend(["--profile", profile])
    try:
        res = subprocess.run(aws_cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        logger.debug("Host AWS CLI unavailable")
        return None
    if res.returncode != 0 or not res.stdout.strip():
        return None
    try:
        data = json.loads(res.stdout)
    except ValueError:
        return None
    access_key = str(data.get("AccessKeyId") or "")
    secret_key = str(data.get("SecretAccessKey") or "")
    if not access_key or not secret_key:
        return None
    return access_key, secret_key, str(data.get("SessionToken") or "")


def _bedrock_token_in_container(container_name: str, profile: str, region: str) -> str | None:
    """Generate the token inside the dev container with ``aws-bedrock-token-generator``."""
    script = (
        "import os; "
        "from aws_bedrock_token_generator import provide_token; "
        "print(provide_token(region=os.environ['AWS_REGION']))"
    )
    cmd = ["docker", "exec"]
    if profile:
        cmd.extend(["-e", f"AWS_PROFILE={profile}"])
    cmd.extend(["-e", f"AWS_REGION={region}", "-e", f"AWS_DEFAULT_REGION={region}"])
    cmd.extend([container_name, "python3", "-c", script])
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        logger.debug("In-container Bedrock token generator unavailable")
        return None
    if res.returncode != 0 or not res.stdout.strip():
        return None
    token = res.stdout.strip().splitlines()[-1].strip()
    return token if token.startswith(BEDROCK_TOKEN_PREFIX) else None


def generate_bedrock_bearer_token(
    *,
    profile: str = "",
    region: str = "us-east-1",
    container_name: str | None = None,
) -> str | None:
    """Generate a short-term Bedrock API key (bearer token) from the active AWS profile.

    The token is the one ``aws_bedrock_token_generator.provide_token`` makes: a
    SigV4 presigned ``CallWithBearerToken`` request for *region*. It lasts
    12 hours, or less when the AWS session ends sooner.

    Credential sources, in order:
    1. botocore on the host, when it is installed.
    2. ``aws-bedrock-token-generator`` inside the dev container (``~/.aws`` is
       bind-mounted there, so an SSO login on the host works).
    3. ``aws configure export-credentials`` from the host AWS CLI v2.
    """
    creds = _bedrock_credentials_via_botocore(profile)
    if creds:
        return _stdlib_sigv4_bedrock_token(
            access_key=creds[0], secret_key=creds[1], session_token=creds[2], region=region
        )

    if container_name:
        token = _bedrock_token_in_container(container_name, profile, region)
        if token:
            return token

    creds = _bedrock_credentials_via_aws_cli(profile)
    if creds:
        return _stdlib_sigv4_bedrock_token(
            access_key=creds[0], secret_key=creds[1], session_token=creds[2], region=region
        )
    return None


def _stdlib_sigv4_bedrock_token(
    *,
    access_key: str,
    secret_key: str,
    session_token: str = "",
    region: str = "us-east-1",
    expires_in: int = BEDROCK_TOKEN_MAX_SECONDS,
    now: datetime.datetime | None = None,
) -> str:
    """Create a short-term Bedrock API key with the Python standard library only.

    The output is the same as ``aws_bedrock_token_generator.provide_token``
    (version 1.1.0): a SigV4 query-signed ``POST https://bedrock.amazonaws.com/
    ?Action=CallWithBearerToken`` for *region* with an empty body, prefixed ``bedrock-api-key-`` and suffixed ``&Version=1`` before base64.
    """
    if expires_in <= 0 or expires_in > BEDROCK_TOKEN_MAX_SECONDS:
        raise ValueError("Bedrock token expiry must be between 1 second and 12 hours")

    stamp = now or datetime.datetime.now(datetime.UTC)
    amz_date = stamp.strftime("%Y%m%dT%H%M%SZ")
    datestamp = stamp.strftime("%Y%m%d")
    host = BEDROCK_TOKEN_HOST
    service = "bedrock"
    credential_scope = f"{datestamp}/{region}/{service}/aws4_request"

    operation_params: list[tuple[str, str]] = [("Action", "CallWithBearerToken")]
    auth_params: list[tuple[str, str]] = [
        ("X-Amz-Algorithm", "AWS4-HMAC-SHA256"),
        ("X-Amz-Credential", f"{access_key}/{credential_scope}"),
        ("X-Amz-Date", amz_date),
        ("X-Amz-Expires", str(expires_in)),
        ("X-Amz-SignedHeaders", "host"),
    ]
    if session_token:
        auth_params.append(("X-Amz-Security-Token", session_token))

    def _encode(pairs: list[tuple[str, str]]) -> str:
        return "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in pairs)

    canonical_querystring = _encode(sorted(operation_params + auth_params))
    canonical_request = "\n".join(
        [
            "POST",
            "/",
            canonical_querystring,
            f"host:{host}\n",
            "host",
            hashlib.sha256(b"").hexdigest(),
        ]
    )
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )

    def _sign(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    k_date = _sign(("AWS4" + secret_key).encode("utf-8"), datestamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    k_signing = _sign(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    presigned = (
        f"{host}/?{_encode(operation_params)}&{_encode(auth_params)}"
        f"&X-Amz-Signature={signature}&Version=1"
    )
    encoded = base64.b64encode(presigned.encode("utf-8")).decode("ascii")
    return f"{BEDROCK_TOKEN_PREFIX}{encoded}"


_generate_token_from_credentials = _stdlib_sigv4_bedrock_token


def resolve_bedrock_bearer_token(
    exec_env: dict[str, str],
    *,
    profile: str = "",
    region: str = "us-east-1",
    generate_if_missing: bool = True,
    container_name: str | None = None,
) -> str | None:
    """Ensure ``AWS_BEARER_TOKEN_BEDROCK`` (and ``BEDROCK_API_KEY``) in *exec_env*.

    1. Checks *exec_env* and ``os.environ`` for ``AWS_BEARER_TOKEN_BEDROCK`` or
       ``BEDROCK_API_KEY``.
    2. If missing and *generate_if_missing* is True, attempts to generate a
       short-term token using the active AWS profile.
    3. Populates both ``AWS_BEARER_TOKEN_BEDROCK`` and ``BEDROCK_API_KEY`` in
       *exec_env* when a token is resolved.
    """
    token = (
        exec_env.get(BEDROCK_BEARER_TOKEN_VAR)
        or exec_env.get(BEDROCK_API_KEY_VAR)
        or os.environ.get(BEDROCK_BEARER_TOKEN_VAR)
        or os.environ.get(BEDROCK_API_KEY_VAR)
    )
    if not token and generate_if_missing:
        effective_profile = profile or exec_env.get("AWS_PROFILE", "")
        effective_region = region or exec_env.get("AWS_REGION", "us-east-1")
        token = generate_bedrock_bearer_token(
            profile=effective_profile,
            region=effective_region,
            container_name=container_name,
        )

    if token:
        exec_env[BEDROCK_BEARER_TOKEN_VAR] = token
        exec_env[BEDROCK_API_KEY_VAR] = token
        return token
    return None


def _split_qualified_model(
    model_id: str,
    default_provider: str,
    known_providers: set[str] | None = None,
) -> tuple[str, str, str]:
    """Normalize *model_id* into ``(qualified_model, provider_id, bare_model_id)``."""
    clean = model_id.strip()
    providers = set(_BUILTIN_PROVIDERS)
    if known_providers:
        providers.update(known_providers)
    if default_provider:
        providers.add(default_provider)

    if "/" in clean:
        prefix, rest = clean.split("/", 1)
        if prefix in providers:
            return clean, prefix, rest

    if default_provider:
        return f"{default_provider}/{clean}", default_provider, clean
    return clean, "", clean


def qualify_model_id(
    model_id: str,
    default_provider: str,
    known_providers: set[str] | None = None,
) -> str:
    """Return ``<provider>/<model>`` for *model_id*, preserving HuggingFace ``Org/Model`` IDs."""
    qualified, _, _ = _split_qualified_model(model_id, default_provider, known_providers)
    return qualified


def _route_mantle_model(
    qualified: str, provider: str, bare: str, region: str = ""
) -> tuple[str, str, str]:
    """Move a Bedrock model to the provider that serves it.

    A bedrock-runtime model also gets the Region's inference profile prefix,
    so ``xai.grok-4.7`` becomes ``us-gov.xai.grok-4.7`` in GovCloud.
    """
    if provider in MANTLE_PROVIDER_IDS and bare:
        routed = mantle_provider_for_model(bare)
        if routed == BEDROCK_RUNTIME_PROVIDER_ID and region:
            bare = with_inference_profile(bare, region)
        if routed != provider or f"{routed}/{bare}" != qualified:
            return f"{routed}/{bare}", routed, bare
    return qualified, provider, bare


def _drop_misrouted_mantle_models(config: dict[str, Any]) -> None:
    """Remove Mantle model entries listed under the provider whose route rejects them.

    Older ai-shell versions put every Mantle model under one ``bedrock-mantle``
    provider on ``/openai/v1``. A deep merge cannot delete those entries, so
    they are removed here.
    """
    providers = config.get("provider")
    if not isinstance(providers, dict):
        return
    for provider_id in MANTLE_PROVIDER_IDS:
        entry = providers.get(provider_id)
        models = entry.get("models") if isinstance(entry, dict) else None
        if not isinstance(models, dict):
            continue
        for model_id in list(models):
            if mantle_provider_for_model(model_id) != provider_id:
                del models[model_id]


def deep_merge_dict(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *patch* into a copy of *base* without clobbering sibling keys."""
    merged: dict[str, Any] = dict(base)
    for key, val in patch.items():
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_dict(merged[key], val)
        else:
            merged[key] = val
    return merged


def build_opencode_config_patch(
    *,
    use_bedrock_mantle: bool = False,
    bedrock_region: str = "",
    aws_region: str = "",
    aws_partition: str = "",
    custom_endpoints: list[CustomEndpoint] | None = None,
    primary_model: str = "",
    subagent_model: str = "",
    default_provider: str = "",
) -> dict[str, Any]:
    """Build the ``opencode.json`` configuration dictionary to merge.

    - When Bedrock is active, configures three ``@ai-sdk/openai-compatible``
      providers with ``{env:AWS_BEARER_TOKEN_BEDROCK}``: ``bedrock-mantle`` on
      ``https://bedrock-mantle.<region>.api.aws/v1`` (gpt-oss and most models),
      ``bedrock-mantle-openai`` on ``.../openai/v1`` (GPT-5.x), and
      ``bedrock-runtime`` on ``https://bedrock-runtime.<region>.amazonaws.com/openai/v1``
      (Grok and any inference profile ID). A model is always routed to the
      provider that serves it.
    - Configures each entry in *custom_endpoints* under ``provider[<name>]`` using
      ``@ai-sdk/openai-compatible``.
    - Routes primary agents (``plan``, ``build``) to *primary_model* and
      subagents (``explore``, ``general``) to *subagent_model*.
    """
    effective_region_arg = bedrock_region or aws_region
    mantle_active = bool(use_bedrock_mantle or bedrock_region)

    endpoints = list(custom_endpoints or [])
    known_providers = {ep.name for ep in endpoints}
    if mantle_active:
        known_providers.update(MANTLE_PROVIDER_IDS)

    resolved_default_provider = default_provider.strip()
    if not resolved_default_provider:
        if mantle_active:
            resolved_default_provider = BEDROCK_MANTLE_PROVIDER_ID
        elif endpoints:
            resolved_default_provider = endpoints[0].name

    effective_primary = primary_model.strip()
    if not effective_primary:
        if mantle_active:
            effective_primary = DEFAULT_BEDROCK_MANTLE_PRIMARY_MODEL
        elif endpoints and endpoints[0].models:
            effective_primary = endpoints[0].models[0]

    effective_subagent = subagent_model.strip()
    if not effective_subagent:
        if mantle_active:
            effective_subagent = DEFAULT_BEDROCK_MANTLE_SUBAGENT_MODEL
        elif effective_primary:
            effective_subagent = effective_primary

    providers_patch: dict[str, Any] = {}
    resolved_region = ""

    if mantle_active:
        resolved_region = resolve_bedrock_mantle_region(
            region=effective_region_arg, partition=aws_partition
        )
        api_key = f"{{env:{BEDROCK_BEARER_TOKEN_VAR}}}"
        providers_patch[BEDROCK_MANTLE_PROVIDER_ID] = {
            "npm": OPENAI_COMPATIBLE_NPM,
            "name": f"Amazon Bedrock Mantle ({resolved_region})",
            "options": {
                "baseURL": bedrock_mantle_base_url(region=resolved_region, partition=aws_partition),
                "apiKey": api_key,
            },
            "models": {m: {"name": m} for m in BEDROCK_MANTLE_DEFAULT_MODELS},
        }
        providers_patch[BEDROCK_MANTLE_OPENAI_PROVIDER_ID] = {
            "npm": OPENAI_COMPATIBLE_NPM,
            "name": f"Amazon Bedrock Mantle OpenAI GPT ({resolved_region})",
            "options": {
                "baseURL": bedrock_mantle_openai_base_url(
                    region=resolved_region, partition=aws_partition
                ),
                "apiKey": api_key,
            },
            "models": {m: {"name": m} for m in BEDROCK_MANTLE_OPENAI_DEFAULT_MODELS},
        }
        runtime_models = [
            with_inference_profile(m, resolved_region) for m in BEDROCK_RUNTIME_DEFAULT_BASE_MODELS
        ]
        providers_patch[BEDROCK_RUNTIME_PROVIDER_ID] = {
            "npm": OPENAI_COMPATIBLE_NPM,
            "name": f"Amazon Bedrock Runtime, Grok ({resolved_region})",
            "options": {
                "baseURL": bedrock_runtime_openai_base_url(
                    region=resolved_region, partition=aws_partition
                ),
                "apiKey": api_key,
            },
            "models": {m: {"name": m} for m in runtime_models},
        }

    for ep in endpoints:
        options: dict[str, Any] = {"baseURL": ep.base_url}
        if ep.api_key_env:
            options["apiKey"] = f"{{env:{ep.api_key_env}}}"
        ep_models: dict[str, dict[str, str]] = {m: {"name": m} for m in ep.models if m}
        providers_patch[ep.name] = {
            "npm": OPENAI_COMPATIBLE_NPM,
            "name": ep.display_name or ep.name,
            "options": options,
            "models": ep_models,
        }

    patch: dict[str, Any] = {}
    agent_patch: dict[str, Any] = {}

    if effective_primary:
        qual_primary, prim_prov, prim_bare = _route_mantle_model(
            *_split_qualified_model(effective_primary, resolved_default_provider, known_providers),
            region=resolved_region,
        )
        patch["model"] = qual_primary
        for agent_name in PRIMARY_AGENTS:
            agent_patch[agent_name] = {"model": qual_primary}
        if prim_prov and prim_prov in providers_patch and prim_bare:
            providers_patch[prim_prov].setdefault("models", {})[prim_bare] = {"name": prim_bare}

    if effective_subagent:
        qual_sub, sub_prov, sub_bare = _route_mantle_model(
            *_split_qualified_model(effective_subagent, resolved_default_provider, known_providers),
            region=resolved_region,
        )
        patch["small_model"] = qual_sub
        for agent_name in SUBAGENTS:
            agent_patch[agent_name] = {"model": qual_sub}
        if sub_prov and sub_prov in providers_patch and sub_bare:
            providers_patch[sub_prov].setdefault("models", {})[sub_bare] = {"name": sub_bare}

    if providers_patch:
        patch["provider"] = providers_patch
    if agent_patch:
        patch["agent"] = agent_patch

    return patch


def sync_opencode_config(
    *,
    config_path: Path | None = None,
    use_bedrock_mantle: bool = False,
    bedrock_region: str = "",
    aws_region: str = "",
    aws_partition: str = "",
    custom_endpoints: list[CustomEndpoint] | None = None,
    primary_model: str = "",
    subagent_model: str = "",
    default_provider: str = "",
) -> dict[str, Any]:
    """Deep-merge provider and agent routing settings into ``opencode.json``.

    Never overwrites unrelated user settings (e.g. ``theme``, ``keybinds``,
    ``mcp``, ``plugin``, or other providers/agent attributes).

    Returns the merged configuration dict.
    """
    target = config_path or (Path.home() / ".config" / "opencode" / "opencode.json")
    target.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    if target.is_file():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not parse existing %s, starting fresh merge: %s", target, exc)

    patch = build_opencode_config_patch(
        use_bedrock_mantle=use_bedrock_mantle,
        bedrock_region=bedrock_region,
        aws_region=aws_region,
        aws_partition=aws_partition,
        custom_endpoints=custom_endpoints,
        primary_model=primary_model,
        subagent_model=subagent_model,
        default_provider=default_provider,
    )

    merged = deep_merge_dict(existing, patch)
    _drop_misrouted_mantle_models(merged)
    merged.setdefault("$schema", OPENCODE_SCHEMA_URL)
    target.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return merged


def opencode_launch_env(
    *,
    claude_compat: bool = False,
    plugins: list[str] | tuple[str, ...] = (),
    instructions: list[str] | tuple[str, ...] = (),
    mcp: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Environment for an OpenCode launch.

    Without *claude_compat* the Claude Code compatibility flags are set (see
    :data:`OPENCODE_NO_CLAUDE_ENV`). *plugins*, *instructions* and *mcp* go in
    ``OPENCODE_CONFIG_CONTENT``, which OpenCode merges over its config files:
    plugin and instruction lists are joined, so the user's own entries stay.
    Nothing is written to ``opencode.json`` or to the project.
    """
    env: dict[str, str] = {} if claude_compat else dict(OPENCODE_NO_CLAUDE_ENV)
    content: dict[str, Any] = {}
    if plugins:
        content["plugin"] = list(plugins)
    if instructions:
        content["instructions"] = list(instructions)
    if mcp:
        content["mcp"] = mcp
    if content:
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps(content, separators=(",", ":"))
    return env


def opencode_local_mcp(command: str, args: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
    """An OpenCode ``mcp`` entry for a local (stdio) server."""
    return {"type": "local", "command": [command, *args], "enabled": True}


def _is_skills_link(path: Path, targets: tuple[tuple[str, ...], ...]) -> bool:
    """True when *path* is a symlink whose target ends with one of *targets*."""
    if not path.is_symlink():
        return False
    try:
        parts = Path(os.readlink(path)).parts
    except OSError:
        return False
    return any(parts[-len(t) :] == t for t in targets)


def remove_skills_bridges(
    project_dir: Path | None = None,
    home_dir: Path | None = None,
) -> list[Path]:
    """Remove the skills symlinks that older ai-shell versions created.

    Older versions linked ``~/.config/opencode/skills`` to ``~/.agents/skills``
    or ``~/.claude/skills``, and ``<project>/.opencode/skills`` to
    ``../.agents/skills``. OpenCode always reads its config directories, so
    those links loaded Claude Code skills even with compatibility off. Only
    a symlink with one of those targets is removed; a real directory, or a
    link the user pointed elsewhere, is left alone.

    Returns the removed paths.
    """
    home = home_dir or Path.home()
    candidates: list[tuple[Path, tuple[tuple[str, ...], ...]]] = [
        (
            home / ".config" / "opencode" / "skills",
            ((".agents", "skills"), (".claude", "skills")),
        )
    ]
    if project_dir is not None:
        candidates.append((project_dir / ".opencode" / "skills", (("..", ".agents", "skills"),)))

    removed: list[Path] = []
    for link, targets in candidates:
        if _is_skills_link(link, targets):
            try:
                link.unlink()
                removed.append(link)
            except OSError as exc:
                logger.debug("Could not remove %s: %s", link, exc)
    return removed
