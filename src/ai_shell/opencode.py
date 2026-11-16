"""OpenCode configuration, Bedrock Mantle endpoints, and multi-model routing.

Manages dynamic generation and non-destructive deep-merging of
``~/.config/opencode/opencode.json`` for:
1. AWS Bedrock Mantle OpenAI-compatible endpoints (Commercial & GovCloud).
2. Custom OpenAI-compatible endpoints (self-hosted vLLM, SGLang, etc.).
3. Primary agent (``plan``, ``build``) and subagent (``explore``, ``general``)
   model routing.
4. Bridging ``.agents/skills`` and ``.claude/skills`` for OpenCode discovery.
"""

from __future__ import annotations

import base64
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
OPENAI_COMPATIBLE_NPM = "@ai-sdk/openai-compatible"

DEFAULT_COMMERCIAL_REGION = "us-east-1"
DEFAULT_GOVCLOUD_REGION = "us-gov-west-1"

DEFAULT_BEDROCK_MANTLE_PRIMARY_MODEL = "openai.gpt-5.4"
DEFAULT_BEDROCK_MANTLE_SUBAGENT_MODEL = "openai.gpt-oss-120b"
BEDROCK_MANTLE_DEFAULT_PRIMARY_MODEL = DEFAULT_BEDROCK_MANTLE_PRIMARY_MODEL
BEDROCK_MANTLE_DEFAULT_SUBAGENT_MODEL = DEFAULT_BEDROCK_MANTLE_SUBAGENT_MODEL
BEDROCK_MANTLE_DEFAULT_MODELS: tuple[str, ...] = (
    DEFAULT_BEDROCK_MANTLE_PRIMARY_MODEL,
    DEFAULT_BEDROCK_MANTLE_SUBAGENT_MODEL,
    "openai.gpt-oss-20b",
)

PRIMARY_AGENTS: tuple[str, ...] = ("plan", "build")
SUBAGENTS: tuple[str, ...] = ("explore", "general")

BEDROCK_BEARER_TOKEN_VAR = "AWS_BEARER_TOKEN_BEDROCK"
BEDROCK_API_KEY_VAR = "BEDROCK_API_KEY"

_BUILTIN_PROVIDERS = frozenset(
    {
        BEDROCK_MANTLE_PROVIDER_ID,
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
    """Construct the Bedrock Project Mantle OpenAI-compatible base URL.

    Returns ``https://bedrock-mantle.<region>.api.aws/openai/v1``.
    """
    resolved_region = resolve_bedrock_mantle_region(region=region, partition=partition)
    return f"https://bedrock-mantle.{resolved_region}.api.aws/openai/v1"


def _presign_bedrock_bearer_token_via_botocore(
    profile: str = "",
    region: str = "us-east-1",
    expires_in: int = 3600,
) -> str | None:
    """Generate a short-term Bedrock bearer token on the host if botocore/aws_bedrock_token_generator is available."""
    try:
        import boto3  # type: ignore[import-not-found,import-untyped]
        from aws_bedrock_token_generator import (  # type: ignore[import-not-found,import-untyped]
            provide_token,
        )

        session = (
            boto3.Session(profile_name=profile, region_name=region)
            if profile
            else boto3.Session(region_name=region)
        )
        creds = session.get_credentials()
        if creds is None:
            return None
        token = provide_token(region=region, aws_credentials_provider=creds)
        return str(token).strip() if token else None
    except Exception:
        pass

    # Fallback: try botocore SigV4 presigning directly if botocore is installed
    try:
        import botocore.auth  # type: ignore[import-not-found,import-untyped]
        import botocore.awsrequest  # type: ignore[import-not-found,import-untyped]
        import botocore.session  # type: ignore[import-not-found,import-untyped]

        bc_session = botocore.session.Session(profile=profile or None)
        creds = bc_session.get_credentials()
        if creds is None:
            return None
        frozen = creds.get_frozen_credentials()
        if not frozen.access_key or not frozen.secret_key:
            return None
        url = f"https://bedrock.amazonaws.com/?Action=CallWithBearerToken&Version=2023-09-30&X-Amz-Expires={expires_in}"
        req = botocore.awsrequest.AWSRequest(
            method="POST",
            url=url,
            headers={"Host": "bedrock.amazonaws.com"},
        )
        signer = botocore.auth.SigV4QueryAuth(
            credentials=frozen,
            service_name="bedrock",
            region_name=region,
            expires=expires_in,
        )
        signer.add_auth(req)
        presigned = req.url
        stripped = re.sub(r"^https?://", "", presigned)
        encoded = base64.b64encode((stripped + "&Version=1").encode("utf-8")).decode("ascii")
        return f"bedrock-api-key-{encoded}"
    except Exception:
        return None


def generate_bedrock_bearer_token(
    *,
    profile: str = "",
    region: str = "us-east-1",
    container_name: str | None = None,
) -> str | None:
    """Generate a short-term Bedrock bearer token using the active AWS profile.

    Attempts in order:
    1. Host Python ``aws_bedrock_token_generator`` / ``botocore`` if installed.
    2. In-container ``python3`` using ``aws_bedrock_token_generator`` (where
       ``~/.aws`` is bind-mounted and the package is installed).
    3. Host AWS CLI ``aws configure export-credentials`` + pure-stdlib SigV4
       presigning (works on any host with AWS CLI v2, zero extra Python deps).
    """
    host_token = _presign_bedrock_bearer_token_via_botocore(profile=profile, region=region)
    if host_token:
        return host_token

    if container_name:
        script = (
            "import os, boto3; "
            "from aws_bedrock_token_generator import provide_token; "
            "prof = os.environ.get('AWS_PROFILE') or None; "
            "reg = os.environ.get('AWS_REGION', 'us-east-1'); "
            "s = boto3.Session(profile_name=prof, region_name=reg); "
            "print(provide_token(region=reg, aws_credentials_provider=s.get_credentials()))"
        )
        cmd = ["docker", "exec"]
        if profile:
            cmd.extend(["-e", f"AWS_PROFILE={profile}"])
        if region:
            cmd.extend(["-e", f"AWS_REGION={region}", "-e", f"AWS_DEFAULT_REGION={region}"])
        cmd.extend([container_name, "python3", "-c", script])
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip().splitlines()[-1].strip()
        except (OSError, subprocess.SubprocessError):
            logger.debug("In-container Bedrock helper unavailable")

    # Host AWS CLI export-credentials fallback
    aws_cmd = ["aws", "configure", "export-credentials", "--format", "process"]
    if profile:
        aws_cmd.extend(["--profile", profile])
    try:
        res = subprocess.run(aws_cmd, capture_output=True, text=True, timeout=15)
        if res.returncode == 0 and res.stdout.strip():
            creds_data = json.loads(res.stdout)
            access_key = creds_data.get("AccessKeyId", "")
            secret_key = creds_data.get("SecretAccessKey", "")
            session_token = creds_data.get("SessionToken", "")
            if access_key and secret_key:
                return _stdlib_sigv4_bedrock_token(
                    access_key=access_key,
                    secret_key=secret_key,
                    session_token=session_token,
                    region=region,
                )
    except (OSError, subprocess.SubprocessError, ValueError):
        logger.debug("Host AWS CLI fallback unavailable")

    return None


def _stdlib_sigv4_bedrock_token(
    *,
    access_key: str,
    secret_key: str,
    session_token: str = "",
    region: str = "us-east-1",
    expires_in: int = 3600,
) -> str:
    """Create a SigV4-presigned Bedrock bearer token using only the Python standard library."""
    import datetime
    import hashlib
    import hmac

    now = datetime.datetime.now(datetime.UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    host = "bedrock.amazonaws.com"
    service = "bedrock"
    credential_scope = f"{datestamp}/{region}/{service}/aws4_request"

    query_params: list[tuple[str, str]] = [
        ("Action", "CallWithBearerToken"),
        ("Version", "2023-09-30"),
        ("X-Amz-Algorithm", "AWS4-HMAC-SHA256"),
        ("X-Amz-Credential", f"{access_key}/{credential_scope}"),
        ("X-Amz-Date", amz_date),
        ("X-Amz-Expires", str(expires_in)),
    ]
    if session_token:
        query_params.append(("X-Amz-Security-Token", session_token))
    query_params.append(("X-Amz-SignedHeaders", "host"))
    query_params.sort(key=lambda item: item[0])

    canonical_querystring = "&".join(
        f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in query_params
    )
    canonical_headers = f"host:{host}\n"
    payload_hash = hashlib.sha256(b"").hexdigest()
    canonical_request = (
        f"POST\n/\n{canonical_querystring}\n{canonical_headers}\nhost\n{payload_hash}"
    )

    string_to_sign = (
        "AWS4-HMAC-SHA256\n"
        f"{amz_date}\n"
        f"{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )

    def _sign(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    k_date = _sign(("AWS4" + secret_key).encode("utf-8"), datestamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    k_signing = _sign(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    presigned_without_scheme = (
        f"{host}/?{canonical_querystring}&X-Amz-Signature={signature}&Version=1"
    )
    encoded = base64.b64encode(presigned_without_scheme.encode("utf-8")).decode("ascii")
    return f"bedrock-api-key-{encoded}"


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

    - Configures ``provider["bedrock-mantle"]`` using ``@ai-sdk/openai-compatible``
      pointing at ``https://bedrock-mantle.<region>.api.aws/openai/v1`` with
      ``{env:AWS_BEARER_TOKEN_BEDROCK}`` when Bedrock Mantle is active.
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
        known_providers.add(BEDROCK_MANTLE_PROVIDER_ID)

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

    if mantle_active:
        resolved_region = resolve_bedrock_mantle_region(
            region=effective_region_arg, partition=aws_partition
        )
        base_url = bedrock_mantle_base_url(region=resolved_region, partition=aws_partition)
        mantle_models: dict[str, dict[str, str]] = {
            m: {"name": m} for m in BEDROCK_MANTLE_DEFAULT_MODELS
        }
        providers_patch[BEDROCK_MANTLE_PROVIDER_ID] = {
            "npm": OPENAI_COMPATIBLE_NPM,
            "name": f"Amazon Bedrock Mantle ({resolved_region})",
            "options": {
                "baseURL": base_url,
                "apiKey": f"{{env:{BEDROCK_BEARER_TOKEN_VAR}}}",
            },
            "models": mantle_models,
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
        qual_primary, prim_prov, prim_bare = _split_qualified_model(
            effective_primary, resolved_default_provider, known_providers
        )
        patch["model"] = qual_primary
        for agent_name in PRIMARY_AGENTS:
            agent_patch[agent_name] = {"model": qual_primary}
        if prim_prov and prim_prov in providers_patch and prim_bare:
            providers_patch[prim_prov].setdefault("models", {})[prim_bare] = {"name": prim_bare}

    if effective_subagent:
        qual_sub, sub_prov, sub_bare = _split_qualified_model(
            effective_subagent, resolved_default_provider, known_providers
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
    merged.setdefault("$schema", OPENCODE_SCHEMA_URL)
    target.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return merged


def bridge_opencode_skills(
    project_dir: Path | None = None,
    home_dir: Path | None = None,
) -> list[Path]:
    """Bridge ``.agents/skills`` and ``.claude/skills`` into OpenCode skill directories.

    Creates non-destructive symlinks (when supported by the OS and when the
    destination does not already exist) so OpenCode discovers both global
    (``~/.agents/skills``) and project-level (``.agents/skills``) skills
    alongside Claude Code.

    Returns the list of created or verified bridge paths.
    """
    home = home_dir or Path.home()
    bridged: list[Path] = []

    opencode_config_dir = home / ".config" / "opencode"
    opencode_config_dir.mkdir(parents=True, exist_ok=True)

    # Global skills bridge: ~/.agents/skills -> ~/.config/opencode/skills
    global_agents_skills = home / ".agents" / "skills"
    global_claude_skills = home / ".claude" / "skills"
    global_opencode_skills = opencode_config_dir / "skills"

    for src in (global_agents_skills, global_claude_skills):
        if src.is_dir():
            if not global_opencode_skills.exists() and not global_opencode_skills.is_symlink():
                try:
                    global_opencode_skills.symlink_to(src, target_is_directory=True)
                    bridged.append(global_opencode_skills)
                except OSError as exc:
                    logger.debug("Could not symlink %s -> %s: %s", global_opencode_skills, src, exc)
            elif global_opencode_skills.exists():
                bridged.append(global_opencode_skills)
            break

    # Project skills bridge: <project>/.agents/skills -> <project>/.opencode/skills (if .opencode exists)
    if project_dir is not None and project_dir.is_dir():
        proj_agents_skills = project_dir / ".agents" / "skills"
        proj_opencode_dir = project_dir / ".opencode"
        proj_opencode_skills = proj_opencode_dir / "skills"
        if proj_agents_skills.is_dir() and proj_opencode_dir.is_dir():
            if not proj_opencode_skills.exists() and not proj_opencode_skills.is_symlink():
                try:
                    proj_opencode_skills.symlink_to(
                        Path("..") / ".agents" / "skills", target_is_directory=True
                    )
                    bridged.append(proj_opencode_skills)
                except OSError as exc:
                    logger.debug("Could not symlink %s: %s", proj_opencode_skills, exc)

    return bridged
