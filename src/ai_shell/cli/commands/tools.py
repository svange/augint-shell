"""AI tool subcommands: claude, codex, opencode, pi, shell."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import uuid
import webbrowser
from collections.abc import Callable
from pathlib import Path

import click
from rich.console import Console

from ai_shell.cli import CONTEXT_SETTINGS
from ai_shell.config import AiShellConfig, load_config
from ai_shell.container import ContainerManager, published_host_port
from ai_shell.defaults import (
    CLAUDE_AUTH_OVERRIDE_VARS,
    CLAUDE_CONFIG_DIR_VAR,
    CLAUDE_DEFAULT_ACCOUNT,
    CLAUDE_OAUTH_TOKEN_VAR,
    CLAUDE_REMOTE_CONTROL_UNSET_VARS,
    build_dev_environment,
    claude_account_slug,
    claude_account_token_var,
    dev_container_name,
    list_claude_accounts,
    list_claude_login_accounts,
    project_dev_port,
    sanitize_project_name,
)
from ai_shell.typeahead import capture_typeahead

logger = logging.getLogger(__name__)
console = Console(stderr=True)

FAST_FAILURE_THRESHOLD = 5.0  # seconds — if claude -c exits faster, retry without -c

# Worktrees are created inside .claude/worktrees/ so they stay within the bind
# mount and remain visible on the host.  The branch name mirrors the directory
# name with a "worktree-" prefix, matching the convention used by ``claude
# --worktree``.
WORKTREE_BASE_DIR = ".claude/worktrees"


def _live_host_port(
    manager: ContainerManager, container_name: str, container_port: int
) -> int | None:
    """Host port actually bound for *container_port* on a running container."""
    return published_host_port(manager, container_name, container_port)


def _print_dev_ports(manager: ContainerManager, container_name: str) -> None:
    """Print dev container port mappings as browsable URLs."""
    port_map = manager.container_ports(container_name)
    if not port_map:
        return
    console.print("[dim]Dev server URLs:[/dim]")
    for container_port, host_addr in port_map.items():
        # host_addr is "0.0.0.0:27431" — extract just the port number
        host_port = host_addr.rsplit(":", 1)[-1]
        label = container_port.split("/")[0]  # "3000/tcp" -> "3000"
        console.print(
            f"  [dim]http://localhost:{host_port}[/dim]  [dim italic]({label})[/dim italic]"
        )


def _generate_worktree_name() -> str:
    """Return a short random hex string for an auto-named worktree."""
    return uuid.uuid4().hex[:8]


def _setup_worktree(container_name: str, container_project_dir: str, name: str) -> str:
    """Create a git worktree inside the container and return its absolute container path.

    The worktree is placed at ``.claude/worktrees/{name}`` relative to the
    project root so it stays inside the Docker bind mount.  If the directory
    already exists the creation step is skipped and the existing worktree is
    reused.  The branch is named ``worktree-{name}``.

    Raises :class:`click.ClickException` when worktree creation fails for an
    unexpected reason.
    """
    worktree_rel = f"{WORKTREE_BASE_DIR}/{name}"
    worktree_abs = f"{container_project_dir}/{worktree_rel}"
    branch = f"worktree-{name}"

    # First attempt: create new worktree + new branch
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-w",
            container_project_dir,
            container_name,
            "git",
            "worktree",
            "add",
            worktree_rel,
            "-b",
            branch,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        # Branch already exists → switch to it without -b
        if "already exists" in stderr or "already checked out" in stderr:
            result2 = subprocess.run(
                [
                    "docker",
                    "exec",
                    "-w",
                    container_project_dir,
                    container_name,
                    "git",
                    "worktree",
                    "add",
                    worktree_rel,
                    branch,
                ],
                capture_output=True,
                text=True,
            )
            stderr2 = result2.stderr.strip()
            if result2.returncode != 0 and "already" not in stderr2:
                raise click.ClickException(f"Failed to create worktree '{name}': {stderr2}")
        # Worktree directory already registered → treat as success
        elif "already" not in stderr:
            raise click.ClickException(f"Failed to create worktree '{name}': {stderr}")

    return worktree_abs


def _inject_mcp_config(
    container_name: str,
    host_path: str,
    container_path: str,
) -> None:
    """Copy an MCP config file from the host into a running container.

    Uses ``docker cp`` so the file is available immediately without
    requiring a mount declared at container creation time.
    """
    # Ensure the parent directory exists inside the container.
    # Use string split (not Path) because container_path is a Linux path
    # and this code runs on Windows where Path would mangle it.
    parent = container_path.rsplit("/", 1)[0]
    subprocess.run(
        ["docker", "exec", container_name, "mkdir", "-p", parent],
        capture_output=True,
    )
    result = subprocess.run(
        ["docker", "cp", host_path, f"{container_name}:{container_path}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning("Failed to copy MCP config into container: %s", result.stderr.strip())


def _check_bedrock_access(
    container_name: str,
    exec_env: dict[str, str],
    model_id: str = "",
    cache_ttl: int = 0,
) -> None:
    """Verify Bedrock is reachable before launching a tool.

    Sends a minimal ``converse`` request inside the container to validate
    the full path: AWS credentials, SCP policies, and model access.
    Raises :class:`click.ClickException` with an actionable message on failure.

    When *cache_ttl* > 0, a successful check is recorded under
    ``~/.cache/ai-shell/bedrock-check/`` and re-checks within the TTL window
    are skipped silently.
    """
    from ai_shell.cache import is_fresh, mark_fresh
    from ai_shell.defaults import DEFAULT_BEDROCK_MODEL

    model = model_id or DEFAULT_BEDROCK_MODEL
    region = exec_env.get("AWS_REGION", "us-east-1")
    profile = exec_env.get("AWS_PROFILE", "")

    cache_key = f"{profile}|{region}|{model}"
    if is_fresh("bedrock-check", cache_key, cache_ttl):
        logger.debug(
            "Bedrock preflight cache fresh (profile=%s, region=%s, model=%s)",
            profile or "default",
            region,
            model,
        )
        return

    console.print(f"Checking Bedrock access (profile={profile or 'default'}, region={region})...")

    invoke_cmd = (
        f"aws bedrock-runtime converse"
        f" --model-id {model}"
        f" --region {region}"
        f' --messages \'[{{"role":"user","content":[{{"text":"ping"}}]}}]\''
        f" --inference-config '{{\"maxTokens\":1}}'"
        f" --output json --no-cli-pager"
    )
    if profile:
        invoke_cmd += f" --profile {profile}"

    args = ["docker", "exec"]
    for key, value in exec_env.items():
        args.extend(["-e", f"{key}={value}"])
    args.extend([container_name, "bash", "-c", invoke_cmd])

    logger.debug("bedrock preflight: %s", " ".join(args))
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise click.ClickException(
            f"Bedrock access check failed (profile={profile or 'default'}, "
            f"region={region}, model={model}).\n"
            f"  {stderr}\n\n"
            "Possible causes:\n"
            f"  - AWS SSO session expired: run 'aws sso login --profile {profile or '<profile>'}' on the host\n"
            "  - SCP or IAM policy denying bedrock:InvokeModel\n"
            "  - Wrong AWS region: ensure Bedrock is available in the configured region"
        )

    mark_fresh("bedrock-check", cache_key)


def _get_manager(
    ctx,
    *,
    bedrock: bool = False,
    bedrock_profile: str = "",
    openai_profile: str = "",
    env_file: Path | None = None,
) -> tuple[ContainerManager, str, dict[str, str], AiShellConfig]:
    """Create ContainerManager from Click context and ensure dev container.

    Returns (manager, container_name, exec_env, config) where exec_env is a
    freshly resolved environment dict from .env / host env, suitable for passing
    as extra_env to exec/run calls so that token updates take effect immediately.

    When *bedrock* is True, ``CLAUDE_CODE_USE_BEDROCK=1`` is injected into
    exec_env and *bedrock_profile* overrides ``AWS_PROFILE`` for the tool
    process (the container-level env retains the infra profile).
    """
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())

    if ctx.obj and ctx.obj.get("skip_updates"):
        config.skip_updates = True

    manager = ContainerManager(config)
    container_name = manager.ensure_dev_container()
    _print_dev_ports(manager, container_name)
    exec_env = build_dev_environment(
        config.extra_env,
        config.project_dir,
        project_name=config.project_name,
        bedrock=bedrock,
        aws_profile=config.ai_profile,
        aws_region=config.aws_region,
        bedrock_profile=bedrock_profile or config.bedrock_profile,
        bedrock_region=config.bedrock_region,
        bedrock_model=config.bedrock_model,
        openai_profile=openai_profile or config.openai_profile,
        env_file=env_file,
    )
    return manager, container_name, exec_env, config


T3_OPTION_HELP = (
    "Start a T3 Code server in the dev container and print a pairing URL/QR, "
    "so the project can be driven from the T3 Code desktop, web or mobile app. "
    "The server outlives this session; rerun the flag to pair another device."
)


def _attach_t3(
    manager: ContainerManager,
    container_name: str,
    config: AiShellConfig,
    exec_env: dict[str, str] | None,
) -> None:
    """Start the T3 Code server for this container and print pairing details."""
    from ai_shell.t3 import T3Error, attach

    try:
        attach(manager, container_name, config, exec_env)
    except T3Error as exc:
        raise click.ClickException(str(exc)) from exc


SHELL_EXPO_OPTION_HELP = (
    "Start an Expo dev server (tunnelled) in the dev container and print the "
    "tunnel URL as a QR code. Not auto-detected here: `shell` is the "
    "maintenance path, so the server only starts when asked."
)

EXPO_OPTION_HELP = (
    "Start an Expo dev server (tunnelled) in the dev container and print the "
    "tunnel URL as a QR code before the session starts, so a phone can be "
    "pointed at the app up front. Auto-detected for real Expo apps; use "
    "--no-expo to suppress. The server outlives this session."
)


def _attach_expo(
    manager: ContainerManager,
    container_name: str,
    config: AiShellConfig,
    exec_env: dict[str, str] | None,
    *,
    use_expo: bool | None,
) -> None:
    """Start the Expo dev server for this container and print the tunnel QR.

    *use_expo* is tri-state: True is an explicit ``--expo``, False an explicit
    ``--no-expo``, and None means auto-detect.  An auto-detected start that
    fails must not stop the agent from launching, so it degrades to a warning;
    an explicit ``--expo`` that fails is an error, because the user asked for
    something that was not delivered.
    """
    if use_expo is False or (use_expo is None and not config.expo_auto):
        return

    from ai_shell.expo import ExpoError, attach

    try:
        attach(manager, container_name, config, exec_env, explicit=bool(use_expo))
    except ExpoError as exc:
        if use_expo:
            raise click.ClickException(str(exc)) from exc
        console.print(f"[yellow]Expo dev server not started:[/yellow] {exc}")


def _bedrock_label(exec_env: dict[str, str]) -> str:
    """Return the user-facing Bedrock suffix for launch messages."""
    profile_label = exec_env.get("AWS_PROFILE", "default")
    region_label = exec_env.get("AWS_REGION", "us-east-1")
    return f" via Bedrock (profile={profile_label}, region={region_label})"


def _configure_local_chrome(
    container_name: str,
    *,
    project_name: str,
    project_dir: Path | str | None,
    chrome_profile: str | None = None,
    chrome_proxy: str | None = None,
) -> tuple[list[str], str, int]:
    """Attach chrome-devtools-mcp to a host Chrome instance.

    Returns the ``--mcp-config`` args for an interactive launch, the config
    path inside the container, and the Chrome debug port (for launch modes
    that cannot take ``--mcp-config``, such as ``claude remote-control``).
    *chrome_proxy* becomes Chrome's ``--proxy-server`` when ai-shell launches it.
    """
    from ai_shell.local_chrome import (
        LocalChromeUnavailable,
        ensure_host_chrome,
        prepare_chrome_mcp,
        start_chrome_proxy,
        write_mcp_config,
    )

    label = f" (profile: {chrome_profile})" if chrome_profile else ""
    if chrome_proxy:
        label += f" (proxy: {chrome_proxy})"
    console.print(f"[dim]Connecting to host Chrome{label}...[/dim]")
    try:
        chrome_port = ensure_host_chrome(
            container_name,
            project_name=project_name,
            project_dir=project_dir,
            **({"profile": chrome_profile} if chrome_profile else {}),
            **({"proxy": chrome_proxy} if chrome_proxy else {}),
        )
    except LocalChromeUnavailable as exc:
        raise click.ClickException(str(exc)) from exc

    console.print(f"[dim]Chrome debug port {chrome_port} reachable.[/dim]")

    # Start TCP proxy: localhost:<port> -> host.docker.internal:<port>
    # Chrome rejects non-localhost Host headers, so the MCP server
    # must connect via localhost.
    start_chrome_proxy(container_name, chrome_port)

    # The server is started once here and asked for Chrome's pages, so a
    # broken bridge fails the launch with the server's own words instead of
    # showing up inside Claude as an MCP server that "failed to start".
    try:
        prepare_chrome_mcp(container_name, chrome_port)
    except LocalChromeUnavailable as exc:
        raise click.ClickException(str(exc)) from exc

    host_mcp_path = write_mcp_config(chrome_port)
    container_mcp_path = "/etc/ai-shell/chrome-mcp.json"
    _inject_mcp_config(container_name, str(host_mcp_path), container_mcp_path)
    console.print("[dim]Chrome DevTools MCP attached and answering.[/dim]")
    return ["--mcp-config", container_mcp_path], container_mcp_path, chrome_port


def _is_named_account(claude_account: str) -> bool:
    """True when a non-default Claude account is selected."""
    return bool(claude_account) and str(claude_account).lower() != CLAUDE_DEFAULT_ACCOUNT


def _account_chrome_profile(claude_account: str) -> str | None:
    """Host Chrome profile slug for *claude_account*; ``None`` keeps the per-project Chrome."""
    if not _is_named_account(claude_account):
        return None
    return str(claude_account)


def _resolve_local_chrome(config: AiShellConfig, cli_flag: bool) -> bool:
    """``--local-chrome`` > ``claude.local_chrome``."""
    return bool(cli_flag or config.local_chrome is True)


def _account_chrome_proxy(config: AiShellConfig, cli_value: str | None = None) -> str | None:
    """``--chrome-proxy`` > ``claude.chrome_proxy``.

    Returns ``None`` when no proxy is configured. The value is Chrome's
    ``--proxy-server`` argument, typically the HTTP proxy of a VPN container
    (``http://127.0.0.1:8888``) on a host whose own address sites refuse.
    """
    if cli_value is not None and cli_value.strip():
        return cli_value.strip()
    if isinstance(config.chrome_proxy, str) and config.chrome_proxy.strip():
        return config.chrome_proxy.strip()
    return None


def _resolve_chrome_proxy(
    manager: ContainerManager,
    config: AiShellConfig,
    cli_value: str | None = None,
    *,
    env_file: Path | None = None,
) -> str | None:
    """The proxy URL for the host Chrome, starting ai-shell's VPN when the value is ``vpn``."""
    from ai_shell.vpn import VPN_PROXY_SENTINEL, VpnUnavailable, ensure_vpn_for_config

    value = _account_chrome_proxy(config, cli_value)
    if value is None or value.lower() != VPN_PROXY_SENTINEL:
        return value
    from ai_shell.cli.commands.vpn import prompt_token

    def echo(line: str) -> None:
        console.print(f"[dim]{line}[/dim]")

    try:
        return ensure_vpn_for_config(
            manager, config, env_file=env_file, prompt_token=prompt_token, echo=echo
        )
    except VpnUnavailable as exc:
        raise click.ClickException(str(exc)) from exc


def _claude_exec_env(
    config: AiShellConfig,
    *,
    use_bedrock: bool,
    cli_profile: str | None,
    claude_account: str,
    env_file: Path | None,
    claude_login: bool = False,
) -> dict[str, str]:
    """Build the exec env for a Claude launch; config errors fail loudly."""
    try:
        return build_dev_environment(
            config.extra_env,
            config.project_dir,
            project_name=config.project_name,
            bedrock=use_bedrock,
            aws_profile=config.ai_profile,
            aws_region=config.aws_region,
            bedrock_profile=cli_profile or config.bedrock_profile,
            bedrock_region=config.bedrock_region,
            bedrock_model=config.bedrock_model,
            claude_account=claude_account,
            claude_login=claude_login,
            env_file=env_file,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


def _claude_account_unset_vars(exec_env: dict[str, str]) -> tuple[str, ...]:
    """Vars to unset in the claude process so the selected account's credential wins.

    ``docker exec -e`` cannot remove variables baked into the container at
    creation, so they are removed from the claude process itself. A login
    profile also needs ``CLAUDE_CODE_OAUTH_TOKEN`` gone, because Claude Code
    ranks it above the login.
    """
    if CLAUDE_CONFIG_DIR_VAR in exec_env:
        return CLAUDE_REMOTE_CONTROL_UNSET_VARS
    if CLAUDE_OAUTH_TOKEN_VAR in exec_env:
        return CLAUDE_AUTH_OVERRIDE_VARS
    return ()


def _unset_prefix(unset_vars: tuple[str, ...]) -> list[str]:
    """``env -u VAR ...`` prefix for *unset_vars*, or nothing."""
    if not unset_vars:
        return []
    return ["env", *(arg for var in unset_vars for arg in ("-u", var))]


def _claude_account_cmd_prefix(exec_env: dict[str, str]) -> list[str]:
    """Return an ``env -u ...`` prefix for the claude command, or nothing."""
    return _unset_prefix(_claude_account_unset_vars(exec_env))


def _claude_account_label(claude_account: str, exec_env: dict[str, str]) -> str:
    if CLAUDE_OAUTH_TOKEN_VAR in exec_env:
        return f" (account={claude_account})"
    if CLAUDE_CONFIG_DIR_VAR in exec_env:
        return f" (account={claude_account}, login profile)"
    return ""


def _print_claude_accounts(config: AiShellConfig, env_file: Path | None) -> None:
    """List the Claude accounts (tokens in .env and login profiles) without secrets."""
    token_accounts = {
        claude_account_slug(name): name
        for name in list_claude_accounts(config.project_dir, env_file)
    }
    login_accounts = {claude_account_slug(name): name for name in list_claude_login_accounts()}
    names = {**login_accounts, **token_accounts}
    accounts = [CLAUDE_DEFAULT_ACCOUNT, *(names[slug] for slug in sorted(names))]
    configured = claude_account_slug(config.claude_account or CLAUDE_DEFAULT_ACCOUNT)
    console.print("[bold]Claude accounts:[/bold]")
    for name in accounts:
        slug = claude_account_slug(name)
        sources: list[str] = []
        if name == CLAUDE_DEFAULT_ACCOUNT:
            sources.append("~/.claude login")
        else:
            if slug in token_accounts:
                sources.append(f"token: {claude_account_token_var(name)}")
            if slug in login_accounts:
                sources.append(
                    f"login profile: ~/.augint/claude-accounts/{claude_account_slug(name)}"
                )
        note = f" [dim]({'; '.join(sources)})[/dim]"
        marker = (
            " [green]<- selected when --account is omitted[/green]" if slug == configured else ""
        )
        console.print(f"  {name}{note}{marker}")
    if len(accounts) == 1:
        console.print(
            "[dim]Pass any name to --account <name> to create a login profile on first use, "
            f"or add {claude_account_token_var('<name>')}=<token from 'claude setup-token'> "
            "to ~/.augint/.env.[/dim]"
        )
    console.print(
        "[dim]Use: ai-shell claude --account <name>          "
        "# token or login profile (created on first use)[/dim]"
    )
    console.print(
        "[dim]     ai-shell claude --account <name> --rc     "
        "# Remote Control (login profile; created on first use)[/dim]"
    )
    console.print(
        "[dim]     ai-shell claude --account <name> --login  # (re)authenticate the login profile[/dim]"
    )


# ``claude auth status`` reports how the session would authenticate. Remote
# Control accepts only a claude.ai subscription login; an older CLI omits the
# field, in which case the exit code is all there is to go on.
CLAUDE_AI_AUTH_METHOD = "claude.ai"
ANTHROPIC_API_HOST = "api.anthropic.com"


def _claude_auth_method(status_output: str) -> str | None:
    """Return ``authMethod`` from ``claude auth status`` JSON, or ``None`` if absent."""
    try:
        data = json.loads(status_output or "")
    except ValueError:
        return None
    method = data.get("authMethod") if isinstance(data, dict) else None
    return method if isinstance(method, str) else None


def _check_remote_control_base_url(exec_env: dict[str, str]) -> None:
    """Fail early when ``ANTHROPIC_BASE_URL`` points away from the Anthropic API.

    Remote Control requires talking to ``api.anthropic.com`` directly, so a
    gateway or proxy URL from ``.env`` or ``extra_env`` can only fail later
    with a less specific error.
    """
    base_url = exec_env.get("ANTHROPIC_BASE_URL", "").strip()
    if not base_url:
        return
    from urllib.parse import urlparse

    host = (urlparse(base_url).hostname or "").lower()
    if host != ANTHROPIC_API_HOST:
        raise click.ClickException(
            f"Remote Control requires the Anthropic API, but ANTHROPIC_BASE_URL={base_url} "
            "points elsewhere (an LLM gateway or proxy). Remove it from .env / extra_env "
            "for --rc."
        )


def _ensure_claude_login(
    manager: ContainerManager,
    container_name: str,
    exec_env: dict[str, str],
    *,
    account_label: str,
    workdir: str | None,
    force: bool,
    chrome_profile: str | None,
    chrome_port: int | None = None,
    require_claude_ai: bool = False,
) -> None:
    """Make sure the Claude process will find a login; run ``claude auth login`` if not.

    Used for login-profile accounts and for Remote Control, which refuses
    API keys and setup-token tokens. ``claude auth status`` exits 0 when some
    credential is present; with *require_claude_ai* (Remote Control) its
    ``authMethod`` must also be ``claude.ai``, because a stored API key or an
    ``apiKeyHelper`` also count as logged in but are rejected by the server.
    The login flow is interactive: Claude prints a URL and waits for the
    code, so it runs on the terminal before the real launch.
    """
    prefix = _unset_prefix(CLAUDE_REMOTE_CONTROL_UNSET_VARS)
    if not _claude_login_needed(
        manager,
        container_name,
        exec_env,
        account_label=account_label,
        workdir=workdir,
        force=force,
        require_claude_ai=require_claude_ai,
    ):
        return
    login_cmd = [*prefix, "claude", "auth", "login"]
    exit_code = _piped_claude_login(
        manager,
        container_name,
        login_cmd,
        exec_env=exec_env,
        workdir=workdir,
        chrome_port=chrome_port,
        chrome_profile=chrome_profile,
    )
    if exit_code is None:
        # No login URL came through the pipe; fall back to Claude's own TTY flow.
        if chrome_profile:
            console.print(
                f"[dim]Open the login URL in the Chrome window for profile '{chrome_profile}' "
                "so the browser session matches the account.[/dim]"
            )
        exit_code, _ = manager.run_interactive(
            container_name, login_cmd, extra_env=exec_env, workdir=workdir
        )
    if exit_code != 0:
        raise click.ClickException(
            f"'claude auth login' failed{account_label}. A claude.ai login is required."
        )


def _claude_login_needed(
    manager: ContainerManager,
    container_name: str,
    exec_env: dict[str, str],
    *,
    account_label: str,
    workdir: str | None,
    force: bool,
    require_claude_ai: bool,
) -> bool:
    """Run ``claude auth status`` and say whether a login must run first (and why)."""
    if force:
        console.print(f"[bold]Running 'claude auth login'{account_label}...[/bold]")
        return True
    prefix = _unset_prefix(CLAUDE_REMOTE_CONTROL_UNSET_VARS)
    status = manager.exec_capture(
        container_name,
        [*prefix, "claude", "auth", "status"],
        extra_env=exec_env,
        workdir=workdir,
    )
    method = _claude_auth_method(status.stdout) if status.returncode == 0 else None
    if status.returncode == 0 and (
        not require_claude_ai or method in (None, CLAUDE_AI_AUTH_METHOD)
    ):
        return False
    if status.returncode == 0:
        console.print(
            f"[yellow]Current credential{account_label} is '{method}', but Remote "
            "Control needs a claude.ai login. Starting 'claude auth login'...[/yellow]"
        )
    else:
        console.print(
            f"[yellow]No claude.ai login found{account_label}. "
            "Starting 'claude auth login'...[/yellow]"
        )
    return True


def _plain_chrome_login(
    manager: ContainerManager,
    container_name: str,
    exec_env: dict[str, str],
    *,
    account_label: str,
    workdir: str | None,
    force: bool,
    require_claude_ai: bool,
    project_name: str,
    project_dir: Path | str | None,
    chrome_profile: str | None,
    chrome_proxy: str | None,
) -> bool:
    """Sign in through the account's Chrome opened WITHOUT the DevTools port.

    Google refuses to sign in inside an automated browser, so with
    ``--local-chrome`` the sign-in page opens in a plain window on the same
    profile directory (through the configured proxy), the code is typed at
    the terminal, and the window is closed again; the debug-port Chrome that
    ``--local-chrome`` opens next reuses the session. A Chrome that already
    holds the profile (a previous session's window) is asked to quit first:
    it is ai-shell's own window. Returns ``True`` when a login ran.
    """
    from ai_shell.local_chrome import LocalChromeUnavailable, PlainChrome, launch_plain_chrome

    if not _claude_login_needed(
        manager,
        container_name,
        exec_env,
        account_label=account_label,
        workdir=workdir,
        force=force,
        require_claude_ai=require_claude_ai,
    ):
        return False
    window: PlainChrome | None = None

    def open_url(url: str) -> bool:
        nonlocal window
        try:
            window = launch_plain_chrome(
                project_name=project_name,
                project_dir=project_dir,
                profile=chrome_profile,
                proxy=chrome_proxy,
                url=url,
                close_running=True,
            )
        except LocalChromeUnavailable as exc:
            console.print(f"[yellow]{exc}[/yellow]")
            console.print("[bold]Open this URL in a browser signed in as the account:[/bold]")
            console.print(url, soft_wrap=True, markup=False, highlight=False)
            return True
        where = f"the Chrome window for '{chrome_profile}'" if chrome_profile else "a Chrome window"
        via = f" through {chrome_proxy}" if chrome_proxy else ""
        console.print(
            f"[bold]Sign-in page opened in {where}{via} (no DevTools port, so Google sign-in "
            "works there).[/bold] Sign in as that account; the browser then shows a code."
        )
        return True

    prefix = _unset_prefix(CLAUDE_REMOTE_CONTROL_UNSET_VARS)
    login_cmd = [*prefix, "claude", "auth", "login"]
    exit_code = _piped_claude_login(
        manager,
        container_name,
        login_cmd,
        exec_env=exec_env,
        workdir=workdir,
        chrome_port=None,
        chrome_profile=chrome_profile,
        open_url=open_url,
    )
    if exit_code is None:
        exit_code, _ = manager.run_interactive(
            container_name, login_cmd, extra_env=exec_env, workdir=workdir
        )
    if window is not None:
        console.print(
            "[dim]Closing the sign-in window so the next launch can reuse its session.[/dim]"
        )
        if not window.close():
            console.print(
                "[yellow]That Chrome window is still open; close it, or the next launch "
                "cannot attach the DevTools port.[/yellow]"
            )
    if exit_code != 0:
        raise click.ClickException(
            f"'claude auth login' failed{account_label}. A claude.ai login is required."
        )
    return True


def _piped_claude_login(
    manager: ContainerManager,
    container_name: str,
    login_cmd: list[str],
    *,
    exec_env: dict[str, str],
    workdir: str | None,
    chrome_port: int | None,
    chrome_profile: str | None,
    open_url: Callable[[str], bool] | None = None,
) -> int | None:
    """Run ``claude auth login`` over pipes from the host (see ``claude_login``).

    The authorize URL never crosses the container TTY: it opens in the
    account's host Chrome window when one is attached, otherwise it is printed
    unwrapped. The code is read from a prompt on the host terminal and piped
    to Claude. Returns the exit code, or ``None`` if no URL appeared.
    *open_url* replaces the default opener.
    """
    from ai_shell.claude_login import open_in_chrome, run_piped_login

    def default_open_url(url: str) -> bool:
        if chrome_port is not None and open_in_chrome(chrome_port, url):
            console.print(
                f"[bold]Sign-in page opened in the Chrome window for '{chrome_profile}'.[/bold] "
                "Sign in there as that account; the browser then shows a code."
            )
            # Google refuses to sign in inside a browser that exposes a DevTools
            # port, so a Google (or Google SSO) account needs another browser:
            # the same URL works on any device, and only the code comes back.
            console.print(
                "[dim]If the account signs in with Google, that window will refuse it "
                '("This browser or app may not be secure"). Open the same URL in any '
                "other browser, on any device, and paste the code here:[/dim]"
            )
            console.print(url, soft_wrap=True, markup=False, highlight=False)
            return True
        console.print("[bold]Open this URL in a browser signed in as the account:[/bold]")
        console.print(url, soft_wrap=True, markup=False, highlight=False)
        return True

    def prompt_code() -> str:
        return str(click.prompt("Paste the code the browser shows", default="", show_default=False))

    def echo(line: str) -> None:
        console.print(line, style="dim", markup=False, highlight=False, soft_wrap=True)

    args = manager.exec_args(
        container_name, login_cmd, extra_env=exec_env, workdir=workdir, stdin=True
    )
    return run_piped_login(
        args, open_url=open_url or default_open_url, prompt_code=prompt_code, echo=echo
    )


def _register_chrome_mcp(
    manager: ContainerManager,
    container_name: str,
    exec_env: dict[str, str],
    *,
    workdir: str,
    chrome_port: int,
) -> None:
    """Register chrome-devtools-mcp in the account's Claude config for this project.

    ``claude remote-control`` refuses global flags such as ``--mcp-config``,
    so the server is stored at ``local`` scope (this project, in the active
    ``CLAUDE_CONFIG_DIR``) with ``claude mcp add-json``. Re-adding an existing
    name fails, so any previous entry is removed first; that also refreshes
    the port if it changed.
    """
    from ai_shell.local_chrome import CHROME_MCP_SERVER_NAME, chrome_mcp_server_spec

    base = ["claude", "mcp"]
    manager.exec_capture(
        container_name,
        [*base, "remove", "--scope", "local", CHROME_MCP_SERVER_NAME],
        extra_env=exec_env,
        workdir=workdir,
    )
    result = manager.exec_capture(
        container_name,
        [
            *base,
            "add-json",
            "--scope",
            "local",
            CHROME_MCP_SERVER_NAME,
            json.dumps(chrome_mcp_server_spec(chrome_port)),
        ],
        extra_env=exec_env,
        workdir=workdir,
    )
    if result.returncode != 0:
        raise click.ClickException(
            "Could not register the Chrome MCP server for Remote Control: "
            f"{(result.stderr or result.stdout or '').strip()}"
        )
    console.print("[dim]Chrome DevTools MCP registered for the Remote Control session.[/dim]")


def _remote_control_cmd(*, name: str, safe: bool, extra_args: tuple[str, ...]) -> list[str]:
    """Build the ``claude remote-control`` command for a server-mode session."""
    cmd = [
        *_unset_prefix(CLAUDE_REMOTE_CONTROL_UNSET_VARS),
        "claude",
        "remote-control",
        "--name",
        name,
    ]
    if not safe:
        cmd.extend(["--permission-mode", "bypassPermissions"])
    cmd.extend(extra_args)
    return cmd


def _launch_loaded_config_claude(
    config: AiShellConfig,
    *,
    safe: bool,
    use_aws: bool,
    cli_profile: str | None,
    extra_args: tuple[str, ...],
    local_chrome: bool = False,
    worktree_name: str | None = None,
    env_file: Path | None = None,
    use_t3: bool = False,
    use_expo: bool | None = None,
    cli_account: str | None = None,
    remote_control: str | None = None,
    force_login: bool = False,
    chrome_proxy: str | None = None,
) -> None:
    """Launch Claude for an already loaded project config.

    *remote_control* switches to ``claude remote-control`` (server mode) with
    the given session name (empty string = derived from project and account).
    *force_login* runs ``claude auth login`` for the selected account before
    the launch. Both use the account's login profile instead of its token.
    *chrome_proxy* (``--chrome-proxy``) overrides the configured proxy for
    the host Chrome that ``--local-chrome`` launches.
    """
    with capture_typeahead() as typeahead:
        use_bedrock = use_aws or config.claude_provider == "aws"
        claude_account = cli_account or config.claude_account
        named_account = _is_named_account(claude_account)
        use_login_profile = named_account and (force_login or remote_control is not None)
        if remote_control is not None and use_bedrock:
            raise click.ClickException(
                "Remote Control needs a claude.ai login on the Anthropic API; "
                "it cannot run via Bedrock (--aws or claude.provider: aws)."
            )
        manager = ContainerManager(config)
        container_name = manager.ensure_dev_container()
        _print_dev_ports(manager, container_name)

        exec_env = _claude_exec_env(
            config,
            use_bedrock=use_bedrock,
            cli_profile=cli_profile,
            claude_account=claude_account,
            env_file=env_file,
            claude_login=use_login_profile,
        )
        if remote_control is not None:
            # Server mode refuses API keys and setup-token tokens outright.
            exec_env = {
                k: v for k, v in exec_env.items() if k not in CLAUDE_REMOTE_CONTROL_UNSET_VARS
            }
            _check_remote_control_base_url(exec_env)
        account_prefix = _claude_account_cmd_prefix(exec_env)
        account_label = _claude_account_label(claude_account, exec_env)
        chrome_profile = _account_chrome_profile(claude_account)

        bedrock_label = ""
        if use_bedrock:
            bedrock_label = _bedrock_label(exec_env)
            _check_bedrock_access(
                container_name,
                exec_env,
                model_id=config.bedrock_model,
                cache_ttl=config.bedrock_check_cache_ttl,
            )

        workdir: str | None = None
        resolved_worktree_name = worktree_name
        if resolved_worktree_name is not None:
            if resolved_worktree_name == "":
                resolved_worktree_name = _generate_worktree_name()
            container_project_dir = f"/root/projects/{config.project_name}"
            workdir = _setup_worktree(container_name, container_project_dir, resolved_worktree_name)
            console.print(
                f"[dim]Worktree: {workdir} (branch: worktree-{resolved_worktree_name})[/dim]"
            )

        if use_t3:
            _attach_t3(manager, container_name, config, exec_env)

        _attach_expo(manager, container_name, config, exec_env, use_expo=use_expo)

        mcp_args: list[str] = []
        chrome_port: int | None = None
        chrome_proxy_url: str | None = None

        # AUTO-UPDATE: Check tool freshness before launch
        manager.ensure_tool_fresh(container_name, "claude")

        needs_login = force_login or remote_control is not None or CLAUDE_CONFIG_DIR_VAR in exec_env
        session_workdir = workdir or f"/root/projects/{config.project_name}"

        remote_cmd: list[str] | None = None
        if remote_control is not None:
            session_name = remote_control or (
                f"{config.project_name} ({claude_account})"
                if named_account
                else config.project_name
            )
            remote_cmd = _remote_control_cmd(name=session_name, safe=safe, extra_args=extra_args)
            console.print(
                f"[bold]Starting Claude Code Remote Control{account_label} "
                f"as '{session_name}' in {container_name}...[/bold]"
            )
            console.print(
                "[dim]Drive it from claude.ai/code or the Claude app signed in to that account. "
                "Ctrl+C stops the server.[/dim]"
            )

    typeahead_bytes = typeahead.bytes()

    # Interactive steps run outside the typeahead capture so they own the TTY.
    # The proxy comes first: "vpn" starts the VPN container and may prompt for
    # the NordVPN token, and it must be known before any window opens.
    if local_chrome:
        chrome_proxy_url = _resolve_chrome_proxy(manager, config, chrome_proxy, env_file=env_file)

    # With --local-chrome the sign-in runs first, in a window WITHOUT the
    # DevTools port (Google refuses automated browsers); the debug-port
    # Chrome opens afterwards on the same profile and reuses the session.
    logged_in_here = False
    if needs_login and local_chrome:
        logged_in_here = _plain_chrome_login(
            manager,
            container_name,
            exec_env,
            account_label=account_label,
            workdir=session_workdir,
            force=force_login,
            require_claude_ai=remote_control is not None,
            project_name=config.project_name,
            project_dir=config.project_dir,
            chrome_profile=chrome_profile,
            chrome_proxy=chrome_proxy_url,
        )

    if local_chrome:
        mcp_args, _, chrome_port = _configure_local_chrome(
            container_name,
            project_name=config.project_name,
            project_dir=config.project_dir,
            chrome_profile=chrome_profile,
            chrome_proxy=chrome_proxy_url,
        )

    safe_cmd: list[str] | None = None
    if remote_cmd is None and safe:
        safe_cmd = [*account_prefix, "claude", *mcp_args, *extra_args]
        console.print(
            f"[bold]Launching Claude Code (safe mode){bedrock_label}{account_label} "
            f"in {container_name}...[/bold]"
        )
    elif remote_cmd is None:
        console.print(
            f"[bold]Launching Claude Code{bedrock_label}{account_label} "
            f"in {container_name}...[/bold]"
        )

    if needs_login and not logged_in_here:
        _ensure_claude_login(
            manager,
            container_name,
            exec_env,
            account_label=account_label,
            workdir=session_workdir,
            force=force_login,
            chrome_profile=chrome_profile if local_chrome else None,
            chrome_port=chrome_port,
            require_claude_ai=remote_control is not None,
        )

    if remote_cmd is not None:
        if chrome_port is not None:
            _register_chrome_mcp(
                manager,
                container_name,
                exec_env,
                workdir=session_workdir,
                chrome_port=chrome_port,
            )
        manager.exec_interactive(
            container_name,
            remote_cmd,
            extra_env=exec_env,
            workdir=workdir,
            typeahead=typeahead_bytes,
        )
        return

    if safe_cmd is not None:
        manager.exec_interactive(
            container_name,
            safe_cmd,
            extra_env=exec_env,
            workdir=workdir,
            typeahead=typeahead_bytes,
        )
        return

    cmd_continue = [
        *account_prefix,
        "claude",
        "--dangerously-skip-permissions",
        "-c",
        *mcp_args,
        *extra_args,
    ]
    exit_code, elapsed = manager.run_interactive(
        container_name,
        cmd_continue,
        extra_env=exec_env,
        workdir=workdir,
        typeahead=typeahead_bytes,
    )

    if exit_code != 0 and elapsed < FAST_FAILURE_THRESHOLD:
        console.print("[yellow]No prior conversation found, starting fresh...[/yellow]")
        cmd_fresh = [
            *account_prefix,
            "claude",
            "--dangerously-skip-permissions",
            *mcp_args,
            *extra_args,
        ]
        # Don't replay typeahead here; the previous attempt already consumed it.
        manager.exec_interactive(container_name, cmd_fresh, extra_env=exec_env, workdir=workdir)
        return

    sys.exit(exit_code)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option("--safe", is_flag=True, default=False, help="Run without permissive flags.")
@click.option("--aws", "use_aws", is_flag=True, default=False, help="Use Amazon Bedrock.")
@click.option("--profile", "cli_profile", default=None, help="AWS profile for Bedrock auth.")
@click.option(
    "--account",
    "cli_account",
    default=None,
    is_flag=False,
    flag_value="",
    help=(
        "Claude account to use. Injects CLAUDE_CODE_OAUTH_TOKEN_<NAME> from .env "
        "as CLAUDE_CODE_OAUTH_TOKEN, or uses ~/.augint/claude-accounts/<name>/ "
        "(created on first use). 'default' uses the ~/.claude login. "
        "Give the flag without a value to list the accounts."
    ),
)
@click.option(
    "--worktree",
    "-w",
    "worktree_name",
    default=None,
    is_flag=False,
    flag_value="",
    help=(
        "Create an isolated git worktree and run Claude in it.  "
        "The value becomes the worktree directory name and branch suffix "
        "(``worktree-<name>``).  A short random name is generated when the "
        "flag is given without a value.  "
        "Worktrees are placed at ``.claude/worktrees/<name>/`` inside the "
        "bind mount so they remain visible on the host."
    ),
)
@click.option(
    "--local-chrome",
    "local_chrome",
    is_flag=True,
    default=False,
    help=(
        "Attach Chrome DevTools MCP to a project-scoped host Chrome session. "
        "ai-shell launches or reuses a separate Windows Chrome profile for "
        "this repo and gives Claude browser control over those tabs."
    ),
)
@click.option(
    "--chrome-proxy",
    "chrome_proxy",
    default=None,
    metavar="URL",
    help=(
        "Proxy for the host Chrome that --local-chrome launches, as Chrome's "
        "--proxy-server value (http://127.0.0.1:8888, socks5://host:port). Use it when "
        "sites refuse the machine's own address (a datacenter box) and a VPN container "
        "exposes a proxy. Default: claude.chrome_proxy / AI_SHELL_CHROME_PROXY."
    ),
)
@click.option(
    "--rc",
    "--remote-control",
    "remote_control",
    default=None,
    is_flag=False,
    flag_value="",
    help=(
        "Start a Claude Code Remote Control server (claude remote-control) instead of "
        "a terminal session, so the project can be driven from claude.ai/code or the "
        "Claude app. An optional value names the session. With --account, the "
        "account's login profile (~/.augint/claude-accounts/<name>) is used because "
        "Remote Control rejects setup-token tokens; the first run asks you to log in."
    ),
)
@click.option(
    "--login",
    "force_login",
    is_flag=True,
    default=False,
    help=(
        "Run 'claude auth login' before launching. With --account, this creates or "
        "refreshes that account's login profile (used by --rc)."
    ),
)
@click.option(
    "--t3",
    "use_t3",
    is_flag=True,
    default=False,
    help=T3_OPTION_HELP,
)
@click.option(
    "--expo/--no-expo",
    "use_expo",
    default=None,
    help=EXPO_OPTION_HELP,
)
@click.option(
    "--env",
    "env_file",
    is_flag=False,
    flag_value=".env",
    default=None,
    help="Load .env into the container (all variables). Defaults to ./.env when flag given without value.",
)
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def claude(
    ctx,
    safe,
    use_aws,
    cli_profile,
    cli_account,
    worktree_name,
    local_chrome,
    chrome_proxy,
    remote_control,
    force_login,
    use_t3,
    use_expo,
    env_file,
    extra_args,
):
    """Launch Claude Code in the dev container."""
    resolved_env = Path(env_file) if env_file else None

    if cli_account == "":
        project = ctx.obj.get("project") if ctx.obj else None
        _print_claude_accounts(
            load_config(project_override=project, project_dir=Path.cwd()), resolved_env
        )
        return

    # Load config for the current project and launch a normal Claude session.
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    local_chrome = _resolve_local_chrome(config, local_chrome)
    _launch_loaded_config_claude(
        config,
        safe=safe,
        use_aws=use_aws,
        cli_profile=cli_profile,
        extra_args=extra_args,
        local_chrome=local_chrome,
        worktree_name=worktree_name,
        env_file=resolved_env,
        use_t3=use_t3,
        use_expo=use_expo,
        cli_account=cli_account,
        remote_control=remote_control,
        force_login=force_login,
        chrome_proxy=chrome_proxy,
    )


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--account",
    "cli_account",
    default=None,
    help=(
        "Open the Chrome window of this Claude account (the one --local-chrome uses "
        "with --account NAME). Without it, the current project's window."
    ),
)
@click.option(
    "--chrome-proxy",
    "chrome_proxy",
    default=None,
    metavar="URL",
    help="Proxy for this window (Chrome --proxy-server value). Default: the configured one.",
)
@click.argument("url", required=False)
@click.pass_context
def chrome(ctx, cli_account, chrome_proxy, url):
    """Open an ai-shell Chrome window WITHOUT the DevTools port, for sign-ins.

    Google refuses to sign in inside a browser that exposes a DevTools port,
    which is what --local-chrome launches. Sign in to Google (or any site that
    refuses an automated browser) here once, close the window, and the next
    --local-chrome launch reuses the session. The window is the same profile
    directory, so nothing else changes.
    """
    from ai_shell.local_chrome import LocalChromeUnavailable, launch_plain_chrome
    from ai_shell.vpn import VPN_PROXY_SENTINEL

    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    account = cli_account or config.claude_account
    profile = _account_chrome_profile(account)
    proxy = _account_chrome_proxy(config, chrome_proxy)
    if proxy is not None and proxy.lower() == VPN_PROXY_SENTINEL:
        proxy = _resolve_chrome_proxy(ContainerManager(config), config, chrome_proxy)
    try:
        window = launch_plain_chrome(
            project_name=config.project_name,
            project_dir=config.project_dir,
            profile=profile,
            proxy=proxy,
            url=url,
        )
    except LocalChromeUnavailable as exc:
        raise click.ClickException(str(exc)) from exc
    label = f"account '{account}'" if profile else f"project '{config.project_name}'"
    proxy_label = f" through {proxy}" if proxy else ""
    console.print(f"[bold]Chrome opened for {label}{proxy_label} (no DevTools port).[/bold]")
    console.print(f"[dim]Profile: {window.profile_dir}[/dim]")
    console.print(
        "[dim]Sign in, then close every window of it before the next --local-chrome launch; "
        "that launch opens the same profile with the DevTools port and keeps the session.[/dim]"
    )


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option("--safe", is_flag=True, default=False, help="Run without permissive flags.")
@click.option("--aws", "use_aws", is_flag=True, default=False, help="Use Amazon Bedrock.")
@click.option("--profile", "cli_profile", default=None, help="AWS profile for Bedrock auth.")
@click.option(
    "--openai-profile",
    "openai_profile",
    default=None,
    help=(
        "OpenAI .env profile name for multi-account switching.  "
        "Store per-account keys in .env as OPENAI_API_KEY_{NAME} "
        "(e.g. OPENAI_API_KEY_WORK, OPENAI_API_KEY_PERSONAL).  "
        "Optionally add OPENAI_ORG_ID_{NAME}.  "
        "Set a default in .ai-shell.yaml under openai.profile or "
        "via AI_SHELL_OPENAI_PROFILE env var."
    ),
)
@click.option(
    "--env",
    "env_file",
    is_flag=False,
    flag_value=".env",
    default=None,
    help="Load .env into the container (all variables). Defaults to ./.env when flag given without value.",
)
@click.option(
    "--t3",
    "use_t3",
    is_flag=True,
    default=False,
    help=T3_OPTION_HELP,
)
@click.option(
    "--expo/--no-expo",
    "use_expo",
    default=None,
    help=EXPO_OPTION_HELP,
)
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def codex(
    ctx,
    safe,
    use_aws,
    cli_profile,
    openai_profile,
    env_file,
    use_t3,
    use_expo,
    extra_args,
):
    """Launch Codex in the dev container."""
    resolved_env = Path(env_file) if env_file else None
    with capture_typeahead() as typeahead:
        project = ctx.obj.get("project") if ctx.obj else None
        config = load_config(project_override=project, project_dir=Path.cwd())
        use_bedrock = use_aws or bool(cli_profile) or bool(config.bedrock_profile)

        manager, name, exec_env, config = _get_manager(
            ctx,
            bedrock=use_bedrock,
            bedrock_profile=cli_profile or config.bedrock_profile,
            openai_profile=openai_profile or config.openai_profile,
            env_file=resolved_env,
        )

        if use_bedrock:
            profile_label = exec_env.get("AWS_PROFILE", "default")
            region_label = exec_env.get("AWS_REGION", "us-east-1")
            bedrock_label = f" via Bedrock (profile={profile_label}, region={region_label})"
            _check_bedrock_access(
                name,
                exec_env,
                model_id=config.bedrock_model,
                cache_ttl=config.bedrock_check_cache_ttl,
            )
        else:
            bedrock_label = ""

        resolved_openai_profile = openai_profile or config.openai_profile
        openai_label = (
            f" (OpenAI profile={resolved_openai_profile})" if resolved_openai_profile else ""
        )

        if use_t3:
            _attach_t3(manager, name, config, exec_env)

        _attach_expo(manager, name, config, exec_env, use_expo=use_expo)

        # AUTO-UPDATE: Check tool freshness before launch
        manager.ensure_tool_fresh(name, "codex")

        cmd = ["codex"]
        if not safe:
            cmd.extend(["--dangerously-bypass-approvals-and-sandbox"])
        cmd.extend(extra_args)
        mode_label = " (safe mode)" if safe else ""
        console.print(
            f"[bold]Launching Codex{mode_label}{bedrock_label}{openai_label} in {name}...[/bold]"
        )
    manager.exec_interactive(name, cmd, extra_env=exec_env, typeahead=typeahead.bytes())


def _cfg_str(config: object, attr: str, default: str = "") -> str:
    """Read a string attribute from *config*, returning *default* for mocks or None."""
    val = getattr(config, attr, default)
    return val if isinstance(val, str) else default


def _region_in_partition(region: str, partition: str) -> str:
    """Return *region*, or ``""`` when it belongs to another partition than *partition*.

    With no *partition*, the region is kept (it then decides the partition).
    """
    from ai_shell.opencode import resolve_aws_partition

    clean = region.strip()
    if not clean or not partition.strip():
        return clean
    try:
        wanted = resolve_aws_partition(partition)
    except ValueError:
        return clean
    return clean if resolve_aws_partition("", clean) == wanted else ""


def _opencode_setup(
    ctx: click.Context,
    use_aws: bool = False,
    cli_profile: str | None = None,
    openai_profile: str | None = None,
    env_file: Path | None = None,
    *,
    aws_partition: str | None = None,
    aws_region: str | None = None,
    generate_token: bool = True,
    cli_model: str | None = None,
    cli_subagent_model: str | None = None,
    cli_endpoints: tuple[str, ...] = (),
    custom_url: str | None = None,
    custom_name: str = "custom",
    custom_key_env: str | None = None,
    custom_models: tuple[str, ...] = (),
    local_chrome: bool = False,
) -> tuple[ContainerManager, str, dict[str, str], AiShellConfig, list[str], str, str, str]:
    """Common setup for opencode commands.

    Returns (manager, name, exec_env, config, cmd_base, bedrock_label,
    openai_label, project_slug).
    """
    import os

    from ai_shell.config import _upsert_custom_endpoint
    from ai_shell.opencode import (
        CustomEndpoint,
        parse_endpoint_spec,
        remove_skills_bridges,
        resolve_bedrock_bearer_token,
        resolve_bedrock_mantle_region,
        sanitize_provider_id,
        sync_opencode_config,
    )

    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())

    cfg_provider = _cfg_str(config, "opencode_provider").strip().lower()
    cfg_partition = _cfg_str(config, "aws_partition").strip()
    cfg_bedrock_profile = _cfg_str(config, "bedrock_profile").strip()
    cfg_bedrock_region = _cfg_str(config, "bedrock_region").strip()
    cfg_aws_region = _cfg_str(config, "aws_region").strip()
    cfg_opencode_region = _cfg_str(config, "opencode_region").strip()
    provider_is_aws = cfg_provider in ("aws", "bedrock", "bedrock-mantle")

    resolved_partition = (aws_partition or cfg_partition).strip()
    resolved_profile = (cli_profile or cfg_bedrock_profile).strip()
    # --aws-region and opencode.aws_region are OpenCode's own and must match
    # the partition. The shared aws.bedrock_region / aws.region are defaults
    # for every tool, so one from the other partition is ignored, not an error.
    explicit_region = (aws_region or cfg_opencode_region).strip()
    inherited_region = _region_in_partition(
        cfg_bedrock_region or (cfg_aws_region if not resolved_partition else ""),
        resolved_partition,
    )

    use_bedrock = bool(
        use_aws
        or cli_profile
        or aws_partition
        or aws_region
        or cfg_bedrock_profile
        or cfg_partition
        or provider_is_aws
    )

    mantle_region = ""
    if use_bedrock:
        try:
            mantle_region = resolve_bedrock_mantle_region(
                region=explicit_region or inherited_region,
                partition=resolved_partition,
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        config.bedrock_region = mantle_region

    manager, name, exec_env, config = _get_manager(
        ctx,
        bedrock=use_bedrock,
        bedrock_profile=resolved_profile,
        openai_profile=openai_profile or _cfg_str(config, "openai_profile"),
        env_file=env_file,
    )

    # Also activate Bedrock Mantle if a bearer token was supplied via .env / host env
    if not use_bedrock and (
        exec_env.get("AWS_BEARER_TOKEN_BEDROCK") or exec_env.get("BEDROCK_API_KEY")
    ):
        use_bedrock = True
        try:
            mantle_region = resolve_bedrock_mantle_region(
                region=explicit_region
                or _region_in_partition(exec_env.get("AWS_REGION", ""), resolved_partition),
                partition=resolved_partition,
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

    if use_bedrock:
        if not mantle_region:
            mantle_region = exec_env.get("AWS_REGION", "us-east-1")
        exec_env["AWS_REGION"] = mantle_region
        exec_env["AWS_DEFAULT_REGION"] = mantle_region
        profile_label = exec_env.get("AWS_PROFILE", "") or "default"
        bedrock_label = f" via Bedrock (profile={profile_label}, region={mantle_region})"

        token = resolve_bedrock_bearer_token(
            exec_env,
            profile=exec_env.get("AWS_PROFILE", ""),
            region=mantle_region,
            container_name=name,
            generate_if_missing=generate_token,
        )
        if not token:
            ttl = getattr(config, "bedrock_check_cache_ttl", 0)
            _check_bedrock_access(
                name,
                exec_env,
                model_id=_cfg_str(config, "bedrock_model"),
                cache_ttl=ttl if isinstance(ttl, int) else 0,
            )
    else:
        bedrock_label = ""

    # Assemble custom OpenAI-compatible endpoints (config + CLI flags)
    raw_cfg_endpoints = getattr(config, "opencode_endpoints", None)
    endpoints: list[CustomEndpoint] = (
        list(raw_cfg_endpoints) if isinstance(raw_cfg_endpoints, list) else []
    )
    for spec in cli_endpoints:
        try:
            _upsert_custom_endpoint(endpoints, parse_endpoint_spec(spec))
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

    if custom_url and custom_url.strip():
        _upsert_custom_endpoint(
            endpoints,
            CustomEndpoint(
                name=sanitize_provider_id(custom_name or "custom"),
                base_url=custom_url.strip(),
                api_key_env=(custom_key_env or "").strip(),
                models=[m.strip() for m in custom_models if m.strip()],
            ),
        )

    # Forward any custom endpoint API key env var from host environment into exec_env
    for ep in endpoints:
        if ep.api_key_env and ep.api_key_env not in exec_env:
            host_val = os.environ.get(ep.api_key_env, "").strip()
            if host_val:
                exec_env[ep.api_key_env] = host_val

    resolved_openai_profile = openai_profile or _cfg_str(config, "openai_profile")
    openai_label = f" (OpenAI profile={resolved_openai_profile})" if resolved_openai_profile else ""

    manager.ensure_tool_fresh(name, "opencode")

    raw_project_dir = getattr(config, "project_dir", None)
    project_dir = (
        raw_project_dir
        if isinstance(raw_project_dir, Path)
        else Path(str(raw_project_dir))
        if isinstance(raw_project_dir, str) and raw_project_dir
        else Path.cwd()
    )
    for link in remove_skills_bridges(project_dir=project_dir):
        console.print(f"[dim]Removed the old skills link {link}.[/dim]")

    exec_env.update(
        _opencode_launch_env(
            manager, name, config, project_dir, local_chrome=local_chrome, env_file=env_file
        )
    )

    primary_model = (cli_model or _cfg_str(config, "opencode_model")).strip()
    subagent_model = (cli_subagent_model or _cfg_str(config, "opencode_subagent_model")).strip()
    default_provider = (
        sanitize_provider_id(cfg_provider)
        if cfg_provider and not provider_is_aws and cfg_provider != "ollama"
        else ""
    )

    cmd_base = ["opencode"]
    if use_bedrock or endpoints or primary_model or subagent_model or default_provider:
        merged_cfg = sync_opencode_config(
            bedrock_region=mantle_region if use_bedrock else "",
            custom_endpoints=endpoints,
            primary_model=primary_model,
            subagent_model=subagent_model,
            default_provider=default_provider,
        )
        selected_model = str(merged_cfg.get("model") or "").strip()
        if selected_model:
            cmd_base.extend(["--model", selected_model])
    else:
        cmd_base.extend(["--model", f"ollama/{config.primary_coding_model}"])

    project_slug = sanitize_project_name(project_dir)

    return manager, name, exec_env, config, cmd_base, bedrock_label, openai_label, project_slug


def _ensure_opencode_password(exec_env: dict[str, str]) -> None:
    """Put a server password in *exec_env* and say how to sign in.

    A password from ``.env`` or the host environment wins. Otherwise ai-shell
    uses the one saved in ``~/.augint/opencode/server-password``.
    """
    from ai_shell.opencode import (
        OPENCODE_DEFAULT_USERNAME,
        OPENCODE_SERVER_PASSWORD_ENV,
        OPENCODE_SERVER_USERNAME_ENV,
        opencode_server_password,
        opencode_server_password_path,
    )

    user = exec_env.get(OPENCODE_SERVER_USERNAME_ENV) or OPENCODE_DEFAULT_USERNAME
    if exec_env.get(OPENCODE_SERVER_PASSWORD_ENV):
        console.print(f"[dim]Password protection enabled (user {user}).[/dim]")
        return
    exec_env[OPENCODE_SERVER_PASSWORD_ENV] = opencode_server_password()
    console.print(
        f"[dim]Password protection enabled: user {user}, password in "
        f"{opencode_server_password_path()}.[/dim]"
    )


def _opencode_launch_env(
    manager: ContainerManager,
    name: str,
    config: AiShellConfig,
    project_dir: Path,
    *,
    local_chrome: bool = False,
    env_file: Path | None = None,
) -> dict[str, str]:
    """Claude Code compatibility flags, plugins, instructions and Chrome MCP for OpenCode.

    The host Chrome uses ``claude.chrome_proxy`` (``AI_SHELL_CHROME_PROXY``) as
    ``ai-shell claude`` does, so ``vpn`` sends only the browser through ai-shell's VPN.
    """
    from ai_shell.opencode import (
        DEFAULT_OPENCODE_INSTRUCTIONS,
        DEFAULT_OPENCODE_PLUGINS,
        PLANNOTATOR_CONTAINER_PORT,
        opencode_launch_env,
        opencode_local_mcp,
    )

    raw_plugins = getattr(config, "opencode_plugins", None)
    plugins = raw_plugins if isinstance(raw_plugins, list) else list(DEFAULT_OPENCODE_PLUGINS)
    raw_instructions = getattr(config, "opencode_instructions", None)
    instructions = (
        raw_instructions
        if isinstance(raw_instructions, list)
        else list(DEFAULT_OPENCODE_INSTRUCTIONS)
    )

    mcp: dict[str, object] | None = None
    if local_chrome or getattr(config, "opencode_local_chrome", False) is True:
        from ai_shell.local_chrome import CHROME_MCP_SERVER_NAME, chrome_mcp_server_spec

        chrome_proxy = _resolve_chrome_proxy(manager, config, env_file=env_file)
        _, _, chrome_port = _configure_local_chrome(
            name,
            project_name=config.project_name,
            project_dir=project_dir,
            chrome_proxy=chrome_proxy,
        )
        spec = chrome_mcp_server_spec(chrome_port)
        raw_args = spec.get("args")
        mcp = {
            CHROME_MCP_SERVER_NAME: opencode_local_mcp(
                str(spec["command"]),
                [str(a) for a in raw_args] if isinstance(raw_args, list) else [],
            )
        }

    if any(p.startswith("@plannotator/opencode") for p in plugins):
        plannotator_port = _live_host_port(
            manager, name, PLANNOTATOR_CONTAINER_PORT
        ) or project_dev_port(
            project_dir,
            PLANNOTATOR_CONTAINER_PORT,
            config.project_name,
            dev_ports=config.dev_ports,
        )
        console.print(f"[dim]Plannotator plan review: http://localhost:{plannotator_port}[/dim]")

    return opencode_launch_env(
        claude_compat=getattr(config, "opencode_claude_compat", False) is True,
        plugins=plugins,
        instructions=instructions,
        mcp=mcp,
    )


@click.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.option("--safe", is_flag=True, default=False, help="Run without permissive flags.")
@click.option(
    "--aws",
    "use_aws",
    is_flag=True,
    default=False,
    help="Use AWS Bedrock Mantle OpenAI-compatible endpoint.",
)
@click.option("--profile", "cli_profile", default=None, help="AWS profile for Bedrock auth.")
@click.option(
    "--aws-profile",
    "cli_aws_profile",
    default=None,
    help="AWS profile for Bedrock auth (alias for --profile).",
)
@click.option(
    "--aws-partition",
    type=click.Choice(["commercial", "govcloud"], case_sensitive=False),
    default=None,
    help="AWS partition for Bedrock Mantle (defaults region to us-east-1 or us-gov-west-1).",
)
@click.option(
    "--aws-region",
    default=None,
    help="AWS region for Bedrock Mantle endpoint (e.g. us-east-1, us-gov-west-1).",
)
@click.option(
    "--generate-token/--no-generate-token",
    "generate_token",
    default=True,
    show_default=True,
    help="Generate a short-term Bedrock bearer token from the active AWS profile when AWS_BEARER_TOKEN_BEDROCK is unset.",
)
@click.option(
    "--model",
    "cli_model",
    default=None,
    help="Primary model for plan and build agents (e.g. openai.gpt-5.6-terra, xai.grok-4.7 or vllm/Qwen/Qwen3-Coder-30B).",
)
@click.option(
    "--subagent-model",
    "cli_subagent_model",
    default=None,
    help="Model for explore and general subagents (e.g. openai.gpt-5.6-luna or vllm/fast-model).",
)
@click.option(
    "--endpoint",
    "cli_endpoints",
    multiple=True,
    metavar="SPEC",
    help=(
        "Add a custom OpenAI-compatible endpoint: "
        "NAME=URL[,model=ID][,api_key_env=ENV]. Repeatable."
    ),
)
@click.option(
    "--custom-url",
    default=None,
    help="Base URL for a custom OpenAI-compatible endpoint (e.g. http://gpu-box:8000/v1).",
)
@click.option(
    "--custom-name",
    default="custom",
    show_default=True,
    help="Provider name for --custom-url.",
)
@click.option(
    "--custom-key-env",
    default=None,
    help="Environment variable holding the API key for --custom-url.",
)
@click.option(
    "--custom-model",
    "custom_models",
    multiple=True,
    help="Model ID served by --custom-url (repeatable).",
)
@click.option(
    "--openai-profile",
    "openai_profile",
    default=None,
    help=(
        "OpenAI .env profile name for multi-account switching.  "
        "Store per-account keys in .env as OPENAI_API_KEY_{NAME} "
        "(e.g. OPENAI_API_KEY_WORK, OPENAI_API_KEY_PERSONAL).  "
        "Optionally add OPENAI_ORG_ID_{NAME}.  "
        "Set a default in .ai-shell.yaml under openai.profile or "
        "via AI_SHELL_OPENAI_PROFILE env var."
    ),
)
@click.option(
    "--t3",
    "use_t3",
    is_flag=True,
    default=False,
    help=T3_OPTION_HELP,
)
@click.option(
    "--expo/--no-expo",
    "use_expo",
    default=None,
    help=EXPO_OPTION_HELP,
)
@click.option("--web", is_flag=True, default=False, help="Launch web UI instead of terminal TUI.")
@click.option(
    "--port",
    "web_port",
    type=int,
    default=4096,
    show_default=True,
    help="Container port for --web mode.",
)
@click.option(
    "--env",
    "env_file",
    is_flag=False,
    flag_value=".env",
    default=None,
    help="Load .env into the container (all variables). Defaults to ./.env when flag given without value.",
)
@click.option(
    "--local-chrome",
    "local_chrome",
    is_flag=True,
    default=False,
    help=(
        "Attach Chrome DevTools MCP to a project-scoped host Chrome session, "
        "so OpenCode can open and inspect pages in it (also opencode.local_chrome)."
    ),
)
@click.pass_context
def opencode(
    ctx,
    safe,
    use_aws,
    cli_profile,
    cli_aws_profile,
    aws_partition,
    aws_region,
    generate_token,
    cli_model,
    cli_subagent_model,
    cli_endpoints,
    custom_url,
    custom_name,
    custom_key_env,
    custom_models,
    openai_profile,
    use_t3,
    use_expo,
    web,
    web_port,
    env_file,
    local_chrome,
):
    """Launch opencode in the dev container."""
    resolved_env = Path(env_file) if env_file else None
    effective_profile = cli_aws_profile or cli_profile
    ctx.ensure_object(dict)
    ctx.obj["use_aws"] = use_aws
    ctx.obj["cli_profile"] = effective_profile
    ctx.obj["aws_partition"] = aws_partition
    ctx.obj["aws_region"] = aws_region
    ctx.obj["generate_token"] = generate_token
    ctx.obj["cli_model"] = cli_model
    ctx.obj["cli_subagent_model"] = cli_subagent_model
    ctx.obj["cli_endpoints"] = cli_endpoints
    ctx.obj["custom_url"] = custom_url
    ctx.obj["custom_name"] = custom_name
    ctx.obj["custom_key_env"] = custom_key_env
    ctx.obj["custom_models"] = custom_models
    ctx.obj["openai_profile"] = openai_profile
    ctx.obj["safe"] = safe
    ctx.obj["env_file"] = resolved_env
    ctx.obj["use_t3"] = use_t3
    ctx.obj["use_expo"] = use_expo
    ctx.obj["local_chrome"] = local_chrome

    if ctx.invoked_subcommand is not None:
        return

    with capture_typeahead() as typeahead:
        manager, name, exec_env, config, cmd, bedrock_label, openai_label, project_slug = (
            _opencode_setup(
                ctx,
                use_aws,
                effective_profile,
                openai_profile,
                env_file=resolved_env,
                aws_partition=aws_partition,
                aws_region=aws_region,
                generate_token=generate_token,
                cli_model=cli_model,
                cli_subagent_model=cli_subagent_model,
                cli_endpoints=cli_endpoints,
                custom_url=custom_url,
                custom_name=custom_name,
                custom_key_env=custom_key_env,
                custom_models=custom_models,
                local_chrome=local_chrome,
            )
        )

        if use_t3:
            _attach_t3(manager, name, config, exec_env)

        _attach_expo(manager, name, config, exec_env, use_expo=use_expo)

        if web:
            cmd.append("web")
            cmd.extend(["--hostname", "0.0.0.0", "--port", str(web_port)])  # nosec B104
            cmd.extend(["--mdns", "--mdns-domain", f"{project_slug}.local"])
            cmd.extend(["--cors", "*"])

            host_port = _live_host_port(manager, name, web_port) or project_dev_port(
                config.project_dir or Path.cwd(),
                web_port,
                config.project_name,
                dev_ports=config.dev_ports,
            )
            console.print(
                f"[bold]Launching opencode web{bedrock_label}{openai_label} in {name}...[/bold]"
            )
            console.print(f"[green bold]Open in browser: http://localhost:{host_port}[/green bold]")
            mdns_name = f"{project_slug}.local"
            console.print(f"[green]mDNS: http://{mdns_name}:{web_port}[/green]")
            _ensure_opencode_password(exec_env)
        else:
            console.print(
                f"[bold]Launching opencode{bedrock_label}{openai_label} in {name}...[/bold]"
            )
    manager.exec_interactive(name, cmd, extra_env=exec_env, typeahead=typeahead.bytes())


@opencode.command()
@click.option(
    "--port",
    type=int,
    default=4096,
    show_default=True,
    help="Container port for the server.",
)
@click.option(
    "--open",
    "open_browser",
    is_flag=True,
    default=False,
    help="Open the web UI in the default browser after starting.",
)
@click.pass_context
def serve(ctx, port: int, open_browser: bool) -> None:
    """Start a headless opencode server."""
    manager, name, exec_env, config, cmd, bedrock_label, openai_label, project_slug = (
        _opencode_setup(
            ctx,
            ctx.obj.get("use_aws", False),
            ctx.obj.get("cli_profile"),
            ctx.obj.get("openai_profile"),
            env_file=ctx.obj.get("env_file"),
            aws_partition=ctx.obj.get("aws_partition"),
            aws_region=ctx.obj.get("aws_region"),
            generate_token=ctx.obj.get("generate_token", True),
            cli_model=ctx.obj.get("cli_model"),
            cli_subagent_model=ctx.obj.get("cli_subagent_model"),
            cli_endpoints=ctx.obj.get("cli_endpoints", ()),
            custom_url=ctx.obj.get("custom_url"),
            custom_name=ctx.obj.get("custom_name", "custom"),
            custom_key_env=ctx.obj.get("custom_key_env"),
            custom_models=ctx.obj.get("custom_models", ()),
            local_chrome=ctx.obj.get("local_chrome", False),
        )
    )

    _ensure_opencode_password(exec_env)
    cmd.append("serve")
    cmd.extend(["--hostname", "0.0.0.0", "--port", str(port)])  # nosec B104
    cmd.extend(["--mdns", "--mdns-domain", f"{project_slug}.local"])
    cmd.extend(["--cors", "*"])

    console.print(
        f"[bold]Starting opencode server{bedrock_label}{openai_label} in {name}...[/bold]"
    )
    manager.exec_detached(name, cmd, extra_env=exec_env)

    cwd = Path.cwd()
    host_port = _live_host_port(manager, name, port) or project_dev_port(
        config.project_dir or cwd, port, config.project_name, dev_ports=config.dev_ports
    )
    mdns_name = f"{project_slug}.local"
    console.print(f"[green bold]Server: http://localhost:{host_port}[/green bold]")
    console.print(f"[green]mDNS:   http://{mdns_name}:{port}[/green]")

    if open_browser:
        webbrowser.open(f"http://localhost:{host_port}")


@opencode.command()
@click.option(
    "--port",
    type=int,
    default=4096,
    show_default=True,
    help="Container port where the server is listening.",
)
@click.pass_context
def attach(ctx, port: int) -> None:
    """Attach a TUI to a running opencode server."""
    with capture_typeahead() as typeahead:
        manager, name, exec_env, _config = _get_manager(ctx, env_file=ctx.obj.get("env_file"))
        _ensure_opencode_password(exec_env)
        cmd = ["opencode", "attach", f"http://localhost:{port}"]
        console.print(f"[bold]Attaching to opencode server on port {port}...[/bold]")
    manager.exec_interactive(name, cmd, extra_env=exec_env, typeahead=typeahead.bytes())


@opencode.command()
@click.pass_context
def status(ctx) -> None:
    """Show the status of a running opencode server."""
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    container_name = dev_container_name(config.project_name, config.project_dir)

    # Check if container is running
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or result.stdout.strip() != "true":
        console.print(f"[red]Container {container_name} is not running.[/red]")
        return

    # Check for opencode processes
    result = subprocess.run(
        ["docker", "exec", container_name, "pgrep", "-af", "opencode"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        console.print(f"[yellow]No opencode processes running in {container_name}.[/yellow]")
        return

    lines = result.stdout.strip().splitlines()
    server_running = False
    server_port = 4096
    attach_count = 0

    for line in lines:
        if "serve" in line or "web" in line:
            server_running = True
            parts = line.split()
            for i, part in enumerate(parts):
                if part == "--port" and i + 1 < len(parts):
                    try:
                        server_port = int(parts[i + 1])
                    except ValueError:
                        pass
        if "attach" in line:
            attach_count += 1

    if server_running:
        # Prefer the live binding (authoritative); fall back to the derived port.
        host_port = None
        result = subprocess.run(
            ["docker", "port", container_name, str(server_port)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                host_port = int(result.stdout.strip().splitlines()[0].rsplit(":", 1)[1])
            except (IndexError, ValueError):
                host_port = None
        if host_port is None:
            host_port = project_dev_port(
                config.project_dir or Path.cwd(),
                server_port,
                config.project_name,
                dev_ports=config.dev_ports,
            )
        project_slug = sanitize_project_name(config.project_dir or Path.cwd())
        mdns_name = f"{project_slug}.local"
        console.print("[green bold]OpenCode server is running[/green bold]")
        console.print(f"  URL:      http://localhost:{host_port}")
        console.print(f"  mDNS:     http://{mdns_name}:{server_port}")
        console.print(f"  Port:     {server_port} (container) -> {host_port} (host)")
        console.print(f"  Terminals: {attach_count} attached")
    else:
        console.print("[yellow]OpenCode processes found but no server detected.[/yellow]")
        for line in lines:
            console.print(f"  [dim]{line}[/dim]")


def _check_ollama_running(container_name: str) -> None:
    """Verify the Ollama container is reachable from the dev container.

    Raises :class:`click.ClickException` with setup instructions on failure.
    """
    result = subprocess.run(
        [
            "docker",
            "exec",
            container_name,
            "curl",
            "-sf",
            "http://host.docker.internal:11434/api/version",
        ],
        capture_output=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise click.ClickException(
            "Ollama is not running. Pi requires a running Ollama instance.\n\n"
            "  Start the LLM stack:  ai-shell llm up\n"
            "  Pull models:          ai-shell llm pull\n\n"
            "Once Ollama is running, retry:  ai-shell pi"
        )


def _ensure_pi_ollama_provider(config: AiShellConfig) -> None:
    """Ensure ``~/.pi/agent/models.json`` has an Ollama provider entry.

    Ollama is not a built-in Pi provider — it must be declared in the global
    models.json.  This always updates the Ollama provider block (keeping the
    model list in sync with config) while preserving any other providers the
    user has added manually.
    """
    models_json = Path.home() / ".pi" / "agent" / "models.json"
    models_json.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if models_json.is_file():
        try:
            existing = json.loads(models_json.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    providers = existing.get("providers", {})
    providers["ollama"] = {
        "baseUrl": "http://host.docker.internal:11434/v1",
        "api": "openai-completions",
        "apiKey": "ollama",
        "compat": {
            "supportsDeveloperRole": False,
            "supportsReasoningEffort": False,
        },
        "models": [{"id": tag} for tag in config.models_to_pull],
    }
    existing["providers"] = providers
    models_json.write_text(json.dumps(existing, indent=2) + "\n")
    console.print(f"[dim]Wrote Ollama provider config to {models_json}[/dim]")


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option("--aws", "use_aws", is_flag=True, default=False, help="Use Amazon Bedrock.")
@click.option("--profile", "cli_profile", default=None, help="AWS profile for Bedrock auth.")
@click.option(
    "--openai-profile",
    "openai_profile",
    default=None,
    help=(
        "OpenAI .env profile name for multi-account switching.  "
        "Store per-account keys in .env as OPENAI_API_KEY_{NAME} "
        "(e.g. OPENAI_API_KEY_WORK, OPENAI_API_KEY_PERSONAL).  "
        "Optionally add OPENAI_ORG_ID_{NAME}.  "
        "Set a default in .ai-shell.yaml under openai.profile or "
        "via AI_SHELL_OPENAI_PROFILE env var."
    ),
)
@click.option(
    "--t3",
    "use_t3",
    is_flag=True,
    default=False,
    help=T3_OPTION_HELP,
)
@click.option(
    "--expo/--no-expo",
    "use_expo",
    default=None,
    help=EXPO_OPTION_HELP,
)
@click.option("--login", "do_login", is_flag=True, default=False, help="Run pi login for OAuth.")
@click.option(
    "--env",
    "env_file",
    is_flag=False,
    flag_value=".env",
    default=None,
    help="Load .env into the container (all variables). Defaults to ./.env when flag given without value.",
)
@click.pass_context
def pi(ctx, use_aws, cli_profile, openai_profile, use_t3, use_expo, do_login, env_file):
    """Launch pi coding agent in the dev container."""
    resolved_env = Path(env_file) if env_file else None
    with capture_typeahead() as typeahead:
        project = ctx.obj.get("project") if ctx.obj else None
        config = load_config(project_override=project, project_dir=Path.cwd())
        use_bedrock = use_aws or bool(cli_profile) or bool(config.bedrock_profile)

        manager, name, exec_env, config = _get_manager(
            ctx,
            bedrock=use_bedrock,
            bedrock_profile=cli_profile or config.bedrock_profile,
            openai_profile=openai_profile or config.openai_profile,
            env_file=resolved_env,
        )

        if do_login:
            console.print("[bold]Running pi login...[/bold]")
            manager.exec_interactive(name, ["pi", "login"], extra_env=exec_env)

        if use_bedrock:
            bedrock_model = config.bedrock_model
            profile_label = exec_env.get("AWS_PROFILE", "default")
            region_label = exec_env.get("AWS_REGION", "us-east-1")
            bedrock_label = (
                f" via Bedrock (profile={profile_label},"
                f" region={region_label}, model={bedrock_model})"
            )
            _check_bedrock_access(
                name,
                exec_env,
                model_id=bedrock_model,
                cache_ttl=config.bedrock_check_cache_ttl,
            )
        else:
            bedrock_model = ""
            bedrock_label = ""
            _check_ollama_running(name)

        resolved_openai_profile = openai_profile or config.openai_profile
        openai_label = (
            f" (OpenAI profile={resolved_openai_profile})" if resolved_openai_profile else ""
        )

        if use_t3:
            _attach_t3(manager, name, config, exec_env)

        _attach_expo(manager, name, config, exec_env, use_expo=use_expo)

        manager.ensure_tool_fresh(name, "pi")

        _ensure_pi_ollama_provider(config)

        cmd = ["pi"]
        if use_bedrock:
            cmd.extend(["--provider", "amazon-bedrock", "--model", bedrock_model])
        console.print(f"[bold]Launching pi{bedrock_label}{openai_label} in {name}...[/bold]")
    manager.exec_interactive(name, cmd, extra_env=exec_env, typeahead=typeahead.bytes())


SUPPORTED_SHELLS: dict[str, str] = {
    "bash": "/bin/bash",
    "zsh": "/usr/bin/zsh",
}


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--env",
    "env_file",
    is_flag=False,
    flag_value=".env",
    default=None,
    help="Load .env into the container (all variables). Defaults to ./.env when flag given without value.",
)
@click.option(
    "--t3",
    "use_t3",
    is_flag=True,
    default=False,
    help=T3_OPTION_HELP,
)
@click.option(
    "--expo/--no-expo",
    "use_expo",
    default=None,
    help=SHELL_EXPO_OPTION_HELP,
)
@click.argument(
    "shell_name",
    required=False,
    type=click.Choice(list(SUPPORTED_SHELLS.keys()), case_sensitive=False),
)
@click.pass_context
def shell(ctx, env_file, use_t3, use_expo, shell_name):
    """Open an interactive shell in the dev container.

    SHELL_NAME is one of bash or zsh.  Defaults to bash if omitted.
    Both shells come pre-configured with modern defaults (Starship
    prompt, useful aliases, history tuning) plus Oh My Zsh for zsh.
    """
    resolved_env = Path(env_file) if env_file else None
    with capture_typeahead() as typeahead:
        manager, name, exec_env, config = _get_manager(ctx, env_file=resolved_env)
        if use_t3:
            _attach_t3(manager, name, config, exec_env)
        # `shell` is the maintenance path — often the place you go to *fix* a
        # broken install — so Expo only starts when explicitly asked, never by
        # auto-detection.
        _attach_expo(manager, name, config, exec_env, use_expo=bool(use_expo))
        if not shell_name:
            shell_name = "bash"
        shell_name = shell_name.lower()
        shell_path = SUPPORTED_SHELLS[shell_name]
        console.print(f"[bold]Opening {shell_name} in {name}...[/bold]")
    manager.exec_interactive(
        name, [shell_path, "-l"], extra_env=exec_env, typeahead=typeahead.bytes()
    )


@click.command(context_settings=CONTEXT_SETTINGS)
def init():
    """Create .ai-shell.yaml config in the current directory."""
    from ai_shell.scaffold import scaffold_global, scaffold_project

    scaffold_global()
    scaffold_project(Path.cwd())
