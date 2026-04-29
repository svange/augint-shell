"""AI tool subcommands: claude, codex, opencode, pi, shell."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import uuid
import webbrowser
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from ai_shell.cli import CONTEXT_SETTINGS
from ai_shell.config import AiShellConfig, load_config
from ai_shell.container import ContainerManager
from ai_shell.defaults import (
    build_dev_environment,
    dev_container_name,
    project_dev_port,
    sanitize_project_name,
    uv_venv_path,
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


def _print_tmux_quick_start() -> None:
    """Print a short tmux quick-start before attaching."""
    console.print("[dim]tmux: mouse click=focus drag=resize wheel=scroll[/dim]")
    console.print("[dim]      Ctrl-a o=pane c=tab Space=layout z=zoom d=detach &=kill-tab[/dim]")


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
) -> None:
    """Verify Bedrock is reachable before launching a tool.

    Sends a minimal ``converse`` request inside the container to validate
    the full path: AWS credentials, SCP policies, and model access.
    Raises :class:`click.ClickException` with an actionable message on failure.
    """
    from ai_shell.defaults import DEFAULT_BEDROCK_MODEL

    model = model_id or DEFAULT_BEDROCK_MODEL
    region = exec_env.get("AWS_REGION", "us-east-1")
    profile = exec_env.get("AWS_PROFILE", "")

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
        openai_profile=openai_profile or config.openai_profile,
        env_file=env_file,
    )
    return manager, container_name, exec_env, config


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
) -> tuple[list[str], str]:
    """Attach chrome-devtools-mcp to a host Chrome instance."""
    from ai_shell.local_chrome import (
        LocalChromeUnavailable,
        ensure_host_chrome,
        start_chrome_proxy,
        write_mcp_config,
    )

    console.print("[dim]Connecting to host Chrome...[/dim]")
    try:
        chrome_port = ensure_host_chrome(
            container_name,
            project_name=project_name,
            project_dir=project_dir,
        )
    except LocalChromeUnavailable as exc:
        raise click.ClickException(str(exc)) from exc

    console.print(f"[dim]Chrome debug port {chrome_port} reachable.[/dim]")

    # Start TCP proxy: localhost:<port> -> host.docker.internal:<port>
    # Chrome rejects non-localhost Host headers, so the MCP server
    # must connect via localhost.
    start_chrome_proxy(container_name, chrome_port)

    host_mcp_path = write_mcp_config(chrome_port)
    container_mcp_path = "/etc/ai-shell/chrome-mcp.json"
    _inject_mcp_config(container_name, str(host_mcp_path), container_mcp_path)
    console.print("[dim]Chrome DevTools MCP attached.[/dim]")
    return ["--mcp-config", container_mcp_path], container_mcp_path


def _launch_loaded_config_claude(
    config: AiShellConfig,
    *,
    safe: bool,
    use_aws: bool,
    cli_profile: str | None,
    extra_args: tuple[str, ...],
    local_chrome: bool = False,
    team_mode: bool = False,
    worktree_name: str | None = None,
    env_file: Path | None = None,
) -> None:
    """Launch Claude for an already loaded project config."""
    with capture_typeahead() as typeahead:
        use_bedrock = use_aws or config.claude_provider == "aws"
        manager = ContainerManager(config)
        container_name = manager.ensure_dev_container()
        _print_dev_ports(manager, container_name)

        exec_env = build_dev_environment(
            config.extra_env,
            config.project_dir,
            project_name=config.project_name,
            bedrock=use_bedrock,
            aws_profile=config.ai_profile,
            aws_region=config.aws_region,
            bedrock_profile=cli_profile or config.bedrock_profile,
            bedrock_region=config.bedrock_region,
            env_file=env_file,
        )

        if team_mode:
            exec_env = dict(exec_env)
            exec_env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"

        bedrock_label = ""
        if use_bedrock:
            bedrock_label = _bedrock_label(exec_env)
            console.print(
                "Checking Bedrock access "
                f"(profile={exec_env.get('AWS_PROFILE', 'default')}, "
                f"region={exec_env.get('AWS_REGION', 'us-east-1')})..."
            )
            _check_bedrock_access(container_name, exec_env)

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

        mcp_args: list[str] = []
        if local_chrome:
            mcp_args, _ = _configure_local_chrome(
                container_name,
                project_name=config.project_name,
                project_dir=config.project_dir,
            )

        # AUTO-UPDATE: Check tool freshness before launch
        manager.ensure_tool_fresh(container_name, "claude")

        safe_cmd: list[str] | None = None
        if safe:
            safe_cmd = ["claude", *mcp_args, *extra_args]
            console.print(
                f"[bold]Launching Claude Code (safe mode){bedrock_label} "
                f"in {container_name}...[/bold]"
            )
        else:
            console.print(
                f"[bold]Launching Claude Code{bedrock_label} in {container_name}...[/bold]"
            )

    typeahead_bytes = typeahead.bytes()

    if safe_cmd is not None:
        manager.exec_interactive(
            container_name,
            safe_cmd,
            extra_env=exec_env,
            workdir=workdir,
            typeahead=typeahead_bytes,
        )
        return

    cmd_continue = ["claude", "--dangerously-skip-permissions", "-c", *mcp_args, *extra_args]
    exit_code, elapsed = manager.run_interactive(
        container_name,
        cmd_continue,
        extra_env=exec_env,
        workdir=workdir,
        typeahead=typeahead_bytes,
    )

    if exit_code != 0 and elapsed < FAST_FAILURE_THRESHOLD:
        console.print("[yellow]No prior conversation found, starting fresh...[/yellow]")
        cmd_fresh = ["claude", "--dangerously-skip-permissions", *mcp_args, *extra_args]
        # Don't replay typeahead here; the previous attempt already consumed it.
        manager.exec_interactive(container_name, cmd_fresh, extra_env=exec_env, workdir=workdir)
        return

    sys.exit(exit_code)


def _load_workspace_repos(workspace_yaml: Path) -> tuple[str, list[dict[str, Any]]]:
    """Parse workspace.yaml and return (workspace_name, repos_list).

    Each repo dict has at least ``name`` and ``path`` keys.
    Raises :class:`click.ClickException` on parse errors.
    """
    import yaml

    try:
        data = yaml.safe_load(workspace_yaml.read_text())
    except Exception as exc:
        raise click.ClickException(f"Failed to parse {workspace_yaml}: {exc}") from exc

    workspace_name: str = data.get("workspace", {}).get("name", workspace_yaml.parent.name)
    repos: list[dict[str, Any]] = data.get("repos", [])
    return workspace_name, repos


def _launch_interactive(
    ctx: click.Context,
    *,
    safe: bool,
    use_aws: bool,
    cli_profile: str | None,
    extra_args: tuple[str, ...],
    worktree_name: str | None = None,
    env_file: Path | None = None,
) -> None:
    """Interactive Claude launcher.

    Walks the user through a guided wizard to configure panes, then launches
    either a normal single session or a customised tmux session.
    """
    from ai_shell.interactive import PaneType, build_interactive_panes, run_interactive_wizard
    from ai_shell.tmux import (
        TMUX_SESSION_PREFIX,
        build_attach_command,
        build_check_session_command,
        build_tmux_commands,
    )

    # Load config early -- needed for prompt defaults and any single-pane launch.
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())

    # Gather workspace repos if available.
    workspace_yaml = Path.cwd() / "workspace.yaml"
    workspace_repos = None
    if workspace_yaml.exists():
        _, workspace_repos = _load_workspace_repos(workspace_yaml)

    # Run the wizard.
    interactive_config = run_interactive_wizard(
        project_name=config.project_name,
        workspace_repos=workspace_repos,
        default_windows=2,
        default_shared_chrome=config.local_chrome is True,
    )
    if interactive_config is None:
        console.print("[dim]Cancelled.[/dim]")
        return

    if interactive_config.pane_count == 1:
        choice = interactive_config.pane_choices[0]

        if choice.pane_type == PaneType.BASH:
            with capture_typeahead() as typeahead:
                manager = ContainerManager(config)
                container_name = manager.ensure_dev_container()
                _print_dev_ports(manager, container_name)
                exec_env = build_dev_environment(
                    config.extra_env,
                    config.project_dir,
                    project_name=config.project_name,
                    aws_profile=config.ai_profile,
                    aws_region=config.aws_region,
                    bedrock_profile=cli_profile or config.bedrock_profile,
                    bedrock_region=config.bedrock_region,
                    env_file=env_file,
                )
                console.print(f"[bold]Launching Bash in {container_name}...[/bold]")
            manager.exec_interactive(
                container_name,
                ["/bin/bash"],
                extra_env=exec_env,
                workdir=f"/root/projects/{config.project_name}",
                typeahead=typeahead.bytes(),
            )
            return

        selected_dir = config.project_dir
        target_label = config.project_name
        if choice.pane_type == PaneType.WORKSPACE_REPO:
            selected_dir = Path.cwd() / choice.repo_path
            if not selected_dir.exists():
                raise click.ClickException(
                    f"Repo directory not found: {selected_dir}\n"
                    "  Run /ai-workspace-sync to clone workspace repos first."
                )
            target_label = choice.repo_name

        console.print(
            f"[dim]Single Claude pane selected -- launching standard session in "
            f"{target_label}[/dim]"
        )
        selected_config = load_config(project_override=project, project_dir=selected_dir)
        _launch_loaded_config_claude(
            selected_config,
            safe=safe,
            use_aws=use_aws,
            cli_profile=cli_profile,
            extra_args=extra_args,
            local_chrome=interactive_config.shared_chrome,
            team_mode=interactive_config.team_mode,
            worktree_name=worktree_name,
        )
        return

    session_name = f"{TMUX_SESSION_PREFIX}-{config.project_name}"
    container_name = dev_container_name(config.project_name, config.project_dir)

    # Check for existing tmux session after the user has actually chosen a
    # multi-pane launch.
    check_cmd = build_check_session_command(container_name, session_name)
    has_session = subprocess.run(check_cmd, capture_output=True).returncode == 0

    if has_session:
        console.print(f"[bold]Found existing tmux session '[cyan]{session_name}[/cyan]'.[/bold]")
        choice = click.prompt(
            "  Reconnect, start fresh, or cancel?",
            type=click.Choice(["reconnect", "fresh", "cancel"], case_sensitive=False),
            default="reconnect",
        )
        if choice == "reconnect":
            # TODO(typeahead): tmux attach in _launch_interactive doesn't
            # replay typeahead bytes; needs a PTY pump around the tmux
            # session. Deferred for now.
            attach_cmd = build_attach_command(container_name, session_name)
            logger.debug("tmux reattach: %s", " ".join(attach_cmd))
            _print_tmux_quick_start()
            sys.stdout.flush()
            sys.stderr.flush()
            attach = subprocess.run(attach_cmd)
            sys.exit(attach.returncode)
        if choice == "cancel":
            return

    # Ensure container is running.
    use_bedrock = use_aws or config.claude_provider == "aws"
    manager = ContainerManager(config)
    container_name = manager.ensure_dev_container()
    _print_dev_ports(manager, container_name)
    exec_env = build_dev_environment(
        config.extra_env,
        config.project_dir,
        project_name=config.project_name,
        bedrock=use_bedrock,
        aws_profile=config.ai_profile,
        aws_region=config.aws_region,
        bedrock_profile=cli_profile or config.bedrock_profile,
        bedrock_region=config.bedrock_region,
        env_file=env_file,
    )

    if use_bedrock:
        _check_bedrock_access(container_name, exec_env)

    # Handle shared Chrome if requested.
    mcp_config_path: str | None = None
    if interactive_config.shared_chrome:
        _, mcp_config_path = _configure_local_chrome(
            container_name,
            project_name=config.project_name,
            project_dir=config.project_dir,
        )

    # Build pane specs.
    container_project_root = f"/root/projects/{config.project_name}"
    panes = build_interactive_panes(
        config=interactive_config,
        project_name=config.project_name,
        container_name=container_name,
        container_project_root=container_project_root,
        safe=safe,
        extra_args=extra_args,
        mcp_config_path=mcp_config_path,
        setup_worktree_fn=_setup_worktree,
    )

    # Build and run tmux commands.
    cmds = build_tmux_commands(container_name, session_name, panes)

    console.print(f"[bold]Launching {len(panes)} panes in tmux session '{session_name}'...[/bold]")

    for cmd_args in cmds[:-1]:
        result = subprocess.run(cmd_args, capture_output=True, text=True)
        if result.returncode != 0 and "kill-session" not in " ".join(cmd_args):
            logger.debug("tmux setup command failed: %s\n%s", cmd_args, result.stderr)

    # TODO(typeahead): multi-pane tmux attach in _launch_interactive doesn't
    # replay typeahead bytes; needs a PTY pump or per-pane send-keys. Deferred.
    final_cmd = cmds[-1]
    logger.debug("tmux attach: %s", " ".join(final_cmd))
    _print_tmux_quick_start()
    sys.stdout.flush()
    sys.stderr.flush()
    attach = subprocess.run(final_cmd)
    sys.exit(attach.returncode)


def _launch_team(
    ctx: click.Context,
    *,
    safe: bool,
    use_aws: bool,
    cli_profile: str | None,
    extra_args: tuple[str, ...],
    env_file: Path | None = None,
) -> None:
    """Launch Claude Code in Agent Teams mode.

    Creates a single Claude Code instance with Agent Teams enabled.  The lead
    agent receives workspace context (repo list from ``workspace.yaml``) and
    manages its own tmux pane splitting for teammates.
    """
    # Gather workspace context if available
    workspace_yaml = Path.cwd() / "workspace.yaml"
    workspace_context = ""
    if workspace_yaml.exists():
        workspace_name, repos = _load_workspace_repos(workspace_yaml)
        repo_lines = "\n".join(
            f"  - {r['name']} ({r.get('repo_type', 'unknown')}): "
            f"/root/projects/{workspace_name}/{r.get('path', './' + r['name']).lstrip('./')}"
            for r in repos
        )
        # Per-repo UV_PROJECT_ENVIRONMENT lines (same scheme as tmux.py)
        env_lines = "\n".join(
            f"  {r['name']}: export UV_PROJECT_ENVIRONMENT={uv_venv_path(r['name'])}" for r in repos
        )
        workspace_context = (
            f"Workspace: {workspace_name}\n"
            f"Repos:\n{repo_lines}\n\n"
            "Spawn teammates for each repo.  Tell each teammate to work in "
            "the directory listed above for their assigned repo.\n\n"
            "IMPORTANT: Each teammate MUST run the following as their first "
            "command before running any uv or python commands:\n"
            f"{env_lines}\n"
            "This isolates each repo's Python virtual environment."
        )

    with capture_typeahead() as typeahead:
        # Load config and create container
        project = ctx.obj.get("project") if ctx.obj else None
        config = load_config(project_override=project, project_dir=Path.cwd())
        use_bedrock = use_aws or config.claude_provider == "aws"

        manager = ContainerManager(config)
        container_name = manager.ensure_dev_container()
        _print_dev_ports(manager, container_name)
        exec_env = build_dev_environment(
            config.extra_env,
            config.project_dir,
            project_name=config.project_name,
            bedrock=use_bedrock,
            aws_profile=config.ai_profile,
            aws_region=config.aws_region,
            bedrock_profile=cli_profile or config.bedrock_profile,
            bedrock_region=config.bedrock_region,
            team_mode=True,
            env_file=env_file,
        )

        if use_bedrock:
            _check_bedrock_access(container_name, exec_env)

        workdir = f"/root/projects/{config.project_name}"

        # Build the claude command -- Agent Teams manages its own tmux panes
        cmd: list[str] = ["claude"]
        if not safe:
            cmd.append("--dangerously-skip-permissions")
        cmd.extend(extra_args)

        # Pass workspace context as the positional prompt argument (NOT -p,
        # which enables non-interactive print mode and would hang).
        if workspace_context:
            cmd.append(workspace_context)

        console.print("[bold]Launching Claude Code in Agent Teams mode (experimental)...[/bold]")
        if workspace_context:
            console.print("[dim]Workspace context provided to team lead[/dim]")

    manager.exec_interactive(
        container_name, cmd, extra_env=exec_env, workdir=workdir, typeahead=typeahead.bytes()
    )


def _launch_single_repo_multi(
    *,
    config: AiShellConfig,
    session_name: str,
    safe: bool,
    use_aws: bool,
    cli_profile: str | None,
    extra_args: tuple[str, ...],
    worktree_name: str | None = None,
    env_file: Path | None = None,
) -> None:
    """Single-repo multi-pane launcher.

    Called when ``--multi`` is used outside a workspace repo (no
    ``workspace.yaml`` in the current directory).  Prompts the user for the
    number of windows (2–4) and creates a separate git worktree for each pane
    so that agents can work on independent branches simultaneously.
    """
    from ai_shell.tmux import (
        PaneSpec,
        build_claude_pane_command,
        build_tmux_commands,
    )

    num_windows = click.prompt(
        "How many windows do you want?",
        type=click.IntRange(2, 4),
        default=2,
    )

    # Resolve the base worktree name (auto-generate when omitted or empty)
    if worktree_name:
        base_name = worktree_name
    else:
        base_name = _generate_worktree_name()

    use_bedrock = use_aws or config.claude_provider == "aws"
    manager = ContainerManager(config)
    container_name = manager.ensure_dev_container()
    _print_dev_ports(manager, container_name)
    exec_env = build_dev_environment(
        config.extra_env,
        config.project_dir,
        project_name=config.project_name,
        bedrock=use_bedrock,
        aws_profile=config.ai_profile,
        aws_region=config.aws_region,
        bedrock_profile=cli_profile or config.bedrock_profile,
        bedrock_region=config.bedrock_region,
        env_file=env_file,
    )

    if use_bedrock:
        _check_bedrock_access(container_name, exec_env)

    container_project_root = f"/root/projects/{config.project_name}"
    panes: list[PaneSpec] = []
    for i in range(1, num_windows + 1):
        wt_name = f"{base_name}-{i}"
        worktree_dir = _setup_worktree(container_name, container_project_root, wt_name)
        pane_cmd = build_claude_pane_command(
            repo_name=config.project_name,
            safe=safe,
            extra_args=extra_args,
            worktree_name=wt_name,
        )
        panes.append(
            PaneSpec(
                name=f"{config.project_name}-{i}",
                command=pane_cmd,
                working_dir=worktree_dir,
            )
        )

    cmds = build_tmux_commands(container_name, session_name, panes)

    console.print(
        f"[bold]Launching {num_windows} Claude Code instances for "
        f"'{config.project_name}' in tmux session '{session_name}'...[/bold]"
    )

    for cmd_args in cmds[:-1]:
        result = subprocess.run(cmd_args, capture_output=True, text=True)
        if result.returncode != 0 and "kill-session" not in " ".join(cmd_args):
            logger.debug("tmux setup command failed: %s\n%s", cmd_args, result.stderr)

    # TODO(typeahead): tmux attach in _launch_single_repo_multi doesn't replay
    # typeahead bytes; needs a PTY pump or per-pane send-keys. Deferred.
    final_cmd = cmds[-1]
    logger.debug("tmux attach: %s", " ".join(final_cmd))
    _print_tmux_quick_start()
    sys.stdout.flush()
    sys.stderr.flush()
    attach = subprocess.run(final_cmd)
    sys.exit(attach.returncode)


def _launch_multi(
    ctx: click.Context,
    *,
    safe: bool,
    use_aws: bool,
    cli_profile: str | None,
    extra_args: tuple[str, ...],
    worktree_name: str | None = None,
    env_file: Path | None = None,
) -> None:
    """Multi-pane Claude launcher.

    In a workspace repo (``workspace.yaml`` present): presents an interactive
    selector and launches one pane per selected repo.

    In a single repo (no ``workspace.yaml``): prompts for the number of
    windows (2–4) and launches that many git worktree instances of the current
    repo so agents can work on independent branches simultaneously.
    """
    from ai_shell.selector import SelectionItem, interactive_multi_select
    from ai_shell.tmux import (
        TMUX_SESSION_PREFIX,
        PaneSpec,
        build_attach_command,
        build_check_session_command,
        build_claude_pane_command,
        build_tmux_commands,
    )

    # Load config early -- needed for both the session check and both flows.
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    session_name = f"{TMUX_SESSION_PREFIX}-{config.project_name}"
    container_name = dev_container_name(config.project_name, config.project_dir)

    # Check for existing tmux session before presenting the selector.
    # The container and session might still be running from a previous
    # invocation (e.g. after the user detached with C-a d or closed
    # the terminal).
    check_cmd = build_check_session_command(container_name, session_name)
    has_session = subprocess.run(check_cmd, capture_output=True).returncode == 0

    if has_session:
        console.print(f"[bold]Found existing tmux session '[cyan]{session_name}[/cyan]'.[/bold]")
        choice = click.prompt(
            "  Reconnect, start fresh, or cancel?",
            type=click.Choice(["reconnect", "fresh", "cancel"], case_sensitive=False),
            default="reconnect",
        )
        if choice == "reconnect":
            # TODO(typeahead): tmux attach in _launch_multi doesn't replay
            # typeahead bytes; needs a PTY pump or per-pane send-keys. Deferred.
            attach_cmd = build_attach_command(container_name, session_name)
            logger.debug("tmux reattach: %s", " ".join(attach_cmd))
            _print_tmux_quick_start()
            sys.stdout.flush()
            sys.stderr.flush()
            attach = subprocess.run(attach_cmd)
            sys.exit(attach.returncode)
        elif choice == "cancel":
            return
        # choice == "fresh": fall through to selector and recreate

    # Single-repo path: no workspace.yaml in the current directory.
    workspace_yaml = Path.cwd() / "workspace.yaml"
    if not workspace_yaml.exists():
        _launch_single_repo_multi(
            config=config,
            session_name=session_name,
            safe=safe,
            use_aws=use_aws,
            cli_profile=cli_profile,
            extra_args=extra_args,
            worktree_name=worktree_name,
            env_file=env_file,
        )
        return

    workspace_name, repos = _load_workspace_repos(workspace_yaml)

    # Build selection items: workspace root first, then each child repo
    items: list[SelectionItem] = [
        SelectionItem(
            label=workspace_name,
            value=".",
            description="workspace root",
        ),
    ]
    for repo in repos:
        items.append(
            SelectionItem(
                label=repo["name"],
                value=repo.get("path", f"./{repo['name']}"),
                description=repo.get("repo_type", ""),
            )
        )

    # Run interactive selector on the host
    selected = interactive_multi_select(items, title="Select repos (up to 4)")

    if not selected:
        console.print("[dim]No repos selected.[/dim]")
        return

    # For a single selection, fall through to normal claude flow
    if len(selected) == 1:
        sel = selected[0]
        sel_path = Path.cwd() / sel.value
        if not sel_path.exists():
            raise click.ClickException(
                f"Repo directory not found: {sel_path}\n"
                "  Run /ai-workspace-sync to clone workspace repos first."
            )
        console.print(f"[dim]Single selection -- launching Claude in {sel.label}[/dim]")
        project = ctx.obj.get("project") if ctx.obj else None
        config = load_config(project_override=project, project_dir=sel_path)
        _launch_loaded_config_claude(
            config,
            safe=safe,
            use_aws=use_aws,
            cli_profile=cli_profile,
            extra_args=extra_args,
            worktree_name=worktree_name,
        )
        return

    # Multi selection (2-4 repos): validate dirs, build tmux session
    missing: list[str] = []
    for sel in selected:
        sel_path = Path.cwd() / sel.value
        if not sel_path.exists():
            missing.append(str(sel_path))
    if missing:
        raise click.ClickException(
            "Repo directories not found:\n"
            + "\n".join(f"  - {p}" for p in missing)
            + "\n\nRun /ai-workspace-sync to clone workspace repos first."
        )

    # config was loaded earlier for the session check; reuse it here
    use_bedrock = use_aws or config.claude_provider == "aws"
    manager = ContainerManager(config)
    container_name = manager.ensure_dev_container()
    _print_dev_ports(manager, container_name)
    exec_env = build_dev_environment(
        config.extra_env,
        config.project_dir,
        project_name=config.project_name,
        bedrock=use_bedrock,
        aws_profile=config.ai_profile,
        aws_region=config.aws_region,
        bedrock_profile=cli_profile or config.bedrock_profile,
        bedrock_region=config.bedrock_region,
        env_file=env_file,
    )

    if use_bedrock:
        _check_bedrock_access(container_name, exec_env)

    # Resolve worktree name (auto-generate if flag given without value)
    wt_name = worktree_name
    if wt_name is not None and wt_name == "":
        wt_name = _generate_worktree_name()

    # Build PaneSpecs
    container_project_root = f"/root/projects/{config.project_name}"
    panes: list[PaneSpec] = []
    for sel in selected:
        if sel.value == ".":
            repo_name = config.project_name
            working_dir = container_project_root
        else:
            repo_name = sel.label
            # Normalize path: strip leading "./"
            rel = sel.value.lstrip("./")
            working_dir = f"{container_project_root}/{rel}"

        # Create a worktree for this repo if --worktree was given
        if wt_name is not None:
            worktree_dir = _setup_worktree(container_name, working_dir, wt_name)
            working_dir = worktree_dir

        pane_cmd = build_claude_pane_command(
            repo_name=repo_name,
            safe=safe,
            extra_args=extra_args,
            worktree_name=wt_name,
        )
        panes.append(PaneSpec(name=repo_name, command=pane_cmd, working_dir=working_dir))

    cmds = build_tmux_commands(container_name, session_name, panes)

    # Execute all setup commands (non-interactive), then attach
    console.print(
        f"[bold]Launching {len(panes)} Claude Code instances in tmux session "
        f"'{session_name}'...[/bold]"
    )

    for cmd_args in cmds[:-1]:
        result = subprocess.run(cmd_args, capture_output=True, text=True)
        # kill-session may fail (no existing session) -- that's fine
        if result.returncode != 0 and "kill-session" not in " ".join(cmd_args):
            logger.debug("tmux setup command failed: %s\n%s", cmd_args, result.stderr)

    # Final command: interactive attach (replaces process)
    # TODO(typeahead): multi-pane tmux attach in _launch_multi doesn't replay
    # typeahead bytes; needs a PTY pump or per-pane send-keys. Deferred.
    final_cmd = cmds[-1]
    logger.debug("tmux attach: %s", " ".join(final_cmd))
    _print_tmux_quick_start()
    sys.stdout.flush()
    sys.stderr.flush()
    attach = subprocess.run(final_cmd)
    sys.exit(attach.returncode)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option("--safe", is_flag=True, default=False, help="Run without permissive flags.")
@click.option("--aws", "use_aws", is_flag=True, default=False, help="Use Amazon Bedrock.")
@click.option("--profile", "cli_profile", default=None, help="AWS profile for Bedrock auth.")
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
    "--multi",
    "do_multi",
    is_flag=True,
    default=False,
    help="Launch Claude Code in multiple workspace repos via tmux.",
)
@click.option(
    "--team",
    "do_team",
    is_flag=True,
    default=False,
    help=(
        "Launch Claude Code in Agent Teams mode (experimental).  "
        "A single Claude instance acts as team lead and spawns teammates, "
        "each working in a different workspace repo.  Requires tmux inside "
        "the container.  Reads workspace.yaml for repo context."
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
    "--interactive",
    "-i",
    "do_interactive",
    is_flag=True,
    default=False,
    help=(
        "Interactive multi-pane setup: walk through a guided menu to "
        "configure windows, teams mode, and shared Chrome before launch. "
        "A single Claude pane falls back to a normal session."
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
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def claude(
    ctx,
    safe,
    use_aws,
    cli_profile,
    worktree_name,
    do_multi,
    do_team,
    local_chrome,
    do_interactive,
    env_file,
    extra_args,
):
    """Launch Claude Code in the dev container."""
    resolved_env = Path(env_file) if env_file else None

    # Incompatibility checks
    if do_team and do_multi:
        raise click.ClickException("--team and --multi are incompatible (both manage tmux).")
    if do_interactive and do_team:
        raise click.ClickException(
            "--interactive and --team are incompatible (interactive handles teams mode itself)."
        )
    if do_interactive and local_chrome:
        raise click.ClickException(
            "--interactive and --local-chrome are incompatible "
            "(interactive handles Chrome setup itself)."
        )

    if do_interactive:
        _launch_interactive(
            ctx,
            safe=safe,
            use_aws=use_aws,
            cli_profile=cli_profile,
            extra_args=extra_args,
            worktree_name=worktree_name,
            env_file=resolved_env,
        )
        return

    if do_multi:
        _launch_multi(
            ctx,
            safe=safe,
            use_aws=use_aws,
            cli_profile=cli_profile,
            extra_args=extra_args,
            worktree_name=worktree_name,
            env_file=resolved_env,
        )
        return

    if do_team:
        _launch_team(
            ctx,
            safe=safe,
            use_aws=use_aws,
            cli_profile=cli_profile,
            extra_args=extra_args,
            env_file=resolved_env,
        )
        return

    # Load config for the current project and launch a normal Claude session.
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    local_chrome = local_chrome or config.local_chrome is True
    _launch_loaded_config_claude(
        config,
        safe=safe,
        use_aws=use_aws,
        cli_profile=cli_profile,
        extra_args=extra_args,
        local_chrome=local_chrome,
        worktree_name=worktree_name,
        env_file=resolved_env,
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
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def codex(
    ctx,
    safe,
    use_aws,
    cli_profile,
    openai_profile,
    env_file,
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
            console.print(
                f"Checking Bedrock access (profile={profile_label}, region={region_label})..."
            )
            _check_bedrock_access(name, exec_env)
        else:
            bedrock_label = ""

        resolved_openai_profile = openai_profile or config.openai_profile
        openai_label = (
            f" (OpenAI profile={resolved_openai_profile})" if resolved_openai_profile else ""
        )

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


def _opencode_setup(
    ctx: click.Context,
    use_aws: bool = False,
    cli_profile: str | None = None,
    openai_profile: str | None = None,
    env_file: Path | None = None,
) -> tuple[ContainerManager, str, dict[str, str], AiShellConfig, list[str], str, str, str]:
    """Common setup for opencode commands.

    Returns (manager, name, exec_env, config, cmd_base, bedrock_label,
    openai_label, project_slug).
    """
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    use_bedrock = use_aws or bool(cli_profile) or bool(config.bedrock_profile)

    manager, name, exec_env, config = _get_manager(
        ctx,
        bedrock=use_bedrock,
        bedrock_profile=cli_profile or config.bedrock_profile,
        openai_profile=openai_profile or config.openai_profile,
        env_file=env_file,
    )

    if use_bedrock:
        profile_label = exec_env.get("AWS_PROFILE", "default")
        region_label = exec_env.get("AWS_REGION", "us-east-1")
        bedrock_label = f" via Bedrock (profile={profile_label}, region={region_label})"
        console.print(
            f"Checking Bedrock access (profile={profile_label}, region={region_label})..."
        )
        _check_bedrock_access(name, exec_env)
    else:
        bedrock_label = ""

    resolved_openai_profile = openai_profile or config.openai_profile
    openai_label = f" (OpenAI profile={resolved_openai_profile})" if resolved_openai_profile else ""

    manager.ensure_tool_fresh(name, "opencode")

    cmd_base = ["opencode"]
    if not use_bedrock:
        cmd_base.extend(["--model", f"ollama/{config.primary_coding_model}"])

    project_slug = sanitize_project_name(config.project_dir or Path.cwd())

    return manager, name, exec_env, config, cmd_base, bedrock_label, openai_label, project_slug


@click.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
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
@click.pass_context
def opencode(
    ctx,
    safe,
    use_aws,
    cli_profile,
    openai_profile,
    web,
    web_port,
    env_file,
):
    """Launch opencode in the dev container."""
    resolved_env = Path(env_file) if env_file else None
    ctx.ensure_object(dict)
    ctx.obj["use_aws"] = use_aws
    ctx.obj["cli_profile"] = cli_profile
    ctx.obj["openai_profile"] = openai_profile
    ctx.obj["safe"] = safe
    ctx.obj["env_file"] = resolved_env

    if ctx.invoked_subcommand is not None:
        return

    with capture_typeahead() as typeahead:
        manager, name, exec_env, config, cmd, bedrock_label, openai_label, project_slug = (
            _opencode_setup(ctx, use_aws, cli_profile, openai_profile, env_file=resolved_env)
        )

        if web:
            cmd.append("web")
            cmd.extend(["--hostname", "0.0.0.0", "--port", str(web_port)])  # nosec B104
            cmd.extend(["--mdns", "--mdns-domain", f"{project_slug}.local"])
            cmd.extend(["--cors", "*"])

            host_port = project_dev_port(
                config.project_dir or Path.cwd(), web_port, config.project_name
            )
            console.print(
                f"[bold]Launching opencode web{bedrock_label}{openai_label} in {name}...[/bold]"
            )
            console.print(f"[green bold]Open in browser: http://localhost:{host_port}[/green bold]")
            mdns_name = f"{project_slug}.local"
            console.print(f"[green]mDNS: http://{mdns_name}:{web_port}[/green]")
            if exec_env.get("OPENCODE_SERVER_PASSWORD"):
                console.print("[dim]Password protection enabled.[/dim]")
            else:
                console.print(
                    "[dim]No auth by default. Set OPENCODE_SERVER_PASSWORD to protect it.[/dim]"
                )
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
        )
    )

    cmd.append("serve")
    cmd.extend(["--hostname", "0.0.0.0", "--port", str(port)])  # nosec B104
    cmd.extend(["--mdns", "--mdns-domain", f"{project_slug}.local"])
    cmd.extend(["--cors", "*"])

    console.print(
        f"[bold]Starting opencode server{bedrock_label}{openai_label} in {name}...[/bold]"
    )
    manager.exec_detached(name, cmd, extra_env=exec_env)

    cwd = Path.cwd()
    host_port = project_dev_port(config.project_dir or cwd, port, config.project_name)
    mdns_name = f"{project_slug}.local"
    console.print(f"[green bold]Server: http://localhost:{host_port}[/green bold]")
    console.print(f"[green]mDNS:   http://{mdns_name}:{port}[/green]")
    if exec_env.get("OPENCODE_SERVER_PASSWORD"):
        console.print("[dim]Password protection enabled.[/dim]")

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
        host_port = project_dev_port(
            config.project_dir or Path.cwd(), server_port, config.project_name
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
@click.option("--login", "do_login", is_flag=True, default=False, help="Run pi login for OAuth.")
@click.option("--doom", is_flag=True, default=False, help="Launch pi-doom (play DOOM via AI).")
@click.option(
    "--env",
    "env_file",
    is_flag=False,
    flag_value=".env",
    default=None,
    help="Load .env into the container (all variables). Defaults to ./.env when flag given without value.",
)
@click.pass_context
def pi(ctx, use_aws, cli_profile, openai_profile, do_login, doom, env_file):
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
            console.print(
                f"Checking Bedrock access (profile={profile_label}, region={region_label})..."
            )
            _check_bedrock_access(name, exec_env, model_id=bedrock_model)
        else:
            bedrock_model = ""
            bedrock_label = ""
            _check_ollama_running(name)

        resolved_openai_profile = openai_profile or config.openai_profile
        openai_label = (
            f" (OpenAI profile={resolved_openai_profile})" if resolved_openai_profile else ""
        )

        manager.ensure_tool_fresh(name, "pi")

        _ensure_pi_ollama_provider(config)

        cmd = ["pi"]
        if doom:
            cmd.extend(["-e", "npm:pi-doom"])
        if use_bedrock:
            cmd.extend(["--provider", "amazon-bedrock", "--model", bedrock_model])
        elif not resolved_openai_profile:
            pi_config = Path(config.project_dir) / ".pi" / "settings.json"
            if not pi_config.is_file():
                console.print(
                    "[yellow]Warning: No Pi project config found (.pi/settings.json). "
                    "Run 'ai-opencodex update' to generate project config.[/yellow]"
                )
        doom_label = " (DOOM)" if doom else ""
        console.print(
            f"[bold]Launching pi{doom_label}{bedrock_label}{openai_label} in {name}...[/bold]"
        )
    manager.exec_interactive(name, cmd, extra_env=exec_env, typeahead=typeahead.bytes())


SUPPORTED_SHELLS: dict[str, str] = {
    "bash": "/bin/bash",
    "zsh": "/usr/bin/zsh",
    "fish": "/usr/bin/fish",
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
@click.argument(
    "shell_name",
    required=False,
    type=click.Choice(list(SUPPORTED_SHELLS.keys()), case_sensitive=False),
)
@click.pass_context
def shell(ctx, env_file, shell_name):
    """Open an interactive shell in the dev container.

    SHELL_NAME is one of bash, zsh, fish.  Defaults to bash if omitted.
    All three shells come pre-configured with modern defaults (Starship
    prompt, useful aliases, history tuning) plus Oh My Zsh for zsh and
    Fisher for fish.
    """
    resolved_env = Path(env_file) if env_file else None
    with capture_typeahead() as typeahead:
        manager, name, exec_env, _config = _get_manager(ctx, env_file=resolved_env)
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
