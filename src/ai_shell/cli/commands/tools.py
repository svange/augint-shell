"""AI tool subcommands: claude, codex, opencode, aider, shell."""

from __future__ import annotations

import logging
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from ai_shell.cli import CONTEXT_SETTINGS
from ai_shell.config import AiShellConfig, load_config
from ai_shell.container import ContainerManager
from ai_shell.defaults import build_dev_environment, dev_container_name, uv_venv_path

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
) -> None:
    """Verify Bedrock is reachable before launching a tool.

    Sends a minimal 1-token ``invoke-model`` request inside the container to
    validate the full path: AWS credentials, SCP policies, and model access.
    Raises :class:`click.ClickException` with an actionable message on failure.
    """
    from ai_shell.defaults import DEFAULT_BEDROCK_MODEL

    region = exec_env.get("AWS_REGION", "us-east-1")
    profile = exec_env.get("AWS_PROFILE", "")

    # Build a tiny invoke-model call to test the full auth chain.
    # Use printf (no trailing newline) and fileb:// (binary blob) -- required by AWS CLI.
    body = (
        '{"anthropic_version":"bedrock-2023-05-31",'
        '"max_tokens":10,'
        '"messages":[{"role":"user","content":"ping"}]}'
    )

    # Write the body to a temp file inside the container, invoke, then clean up
    write_cmd = f"printf '%s' '{body}' > /tmp/_bedrock_check.json"
    invoke_cmd = (
        f"aws bedrock-runtime invoke-model"
        f" --model-id {DEFAULT_BEDROCK_MODEL}"
        f" --region {region}"
        f" --content-type application/json"
        f" --accept application/json"
        f" --body fileb:///tmp/_bedrock_check.json"
        f" /tmp/_bedrock_check_out.json"
    )
    if profile:
        invoke_cmd += f" --profile {profile}"
    cleanup_cmd = "rm -f /tmp/_bedrock_check.json /tmp/_bedrock_check_out.json"
    shell_cmd = f"{write_cmd} && {invoke_cmd}; rc=$?; {cleanup_cmd}; exit $rc"

    args = ["docker", "exec"]
    for key, value in exec_env.items():
        args.extend(["-e", f"{key}={value}"])
    args.extend([container_name, "bash", "-c", shell_cmd])

    logger.debug("bedrock preflight: %s", " ".join(args))
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise click.ClickException(
            f"Bedrock access check failed (profile={profile or 'default'}, "
            f"region={region}, model={DEFAULT_BEDROCK_MODEL}).\n"
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

    # AUTO-UPDATE: Apply --orig-image and --skip-updates flags from root CLI
    if ctx.obj and ctx.obj.get("orig_image"):
        from ai_shell import __version__

        config.image_tag = __version__
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
) -> None:
    """Launch Claude for an already loaded project config."""
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
        console.print(f"[dim]Worktree: {workdir} (branch: worktree-{resolved_worktree_name})[/dim]")

    mcp_args: list[str] = []
    if local_chrome:
        mcp_args, _ = _configure_local_chrome(
            container_name,
            project_name=config.project_name,
            project_dir=config.project_dir,
        )

    # AUTO-UPDATE: Check tool freshness before launch
    manager.ensure_tool_fresh(container_name, "claude")

    if safe:
        cmd = ["claude", *mcp_args, *extra_args]
        console.print(
            f"[bold]Launching Claude Code (safe mode){bedrock_label} in {container_name}...[/bold]"
        )
        manager.exec_interactive(container_name, cmd, extra_env=exec_env, workdir=workdir)
        return

    cmd_continue = ["claude", "--dangerously-skip-permissions", "-c", *mcp_args, *extra_args]
    console.print(f"[bold]Launching Claude Code{bedrock_label} in {container_name}...[/bold]")
    exit_code, elapsed = manager.run_interactive(
        container_name, cmd_continue, extra_env=exec_env, workdir=workdir
    )

    if exit_code != 0 and elapsed < FAST_FAILURE_THRESHOLD:
        console.print("[yellow]No prior conversation found, starting fresh...[/yellow]")
        cmd_fresh = ["claude", "--dangerously-skip-permissions", *mcp_args, *extra_args]
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
            )
            console.print(f"[bold]Launching Bash in {container_name}...[/bold]")
            manager.exec_interactive(
                container_name,
                ["/bin/bash"],
                extra_env=exec_env,
                workdir=f"/root/projects/{config.project_name}",
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
        team_mode=True,
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

    manager.exec_interactive(container_name, cmd, extra_env=exec_env, workdir=workdir)


def _launch_single_repo_multi(
    *,
    config: AiShellConfig,
    session_name: str,
    safe: bool,
    use_aws: bool,
    cli_profile: str | None,
    extra_args: tuple[str, ...],
    worktree_name: str | None = None,
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
    extra_args,
):
    """Launch Claude Code in the dev container."""
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
        )
        return

    if do_team:
        _launch_team(
            ctx,
            safe=safe,
            use_aws=use_aws,
            cli_profile=cli_profile,
            extra_args=extra_args,
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
    )


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option("--safe", is_flag=True, default=False, help="Run without permissive flags.")
@click.option("--aws", "use_aws", is_flag=True, default=False, help="Use Amazon Bedrock.")
@click.option("--profile", "cli_profile", default=None, help="AWS profile for Bedrock auth.")
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def codex(
    ctx,
    safe,
    use_aws,
    cli_profile,
    extra_args,
):
    """Launch Codex in the dev container."""
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    use_bedrock = use_aws

    manager, name, exec_env, config = _get_manager(
        ctx,
        bedrock=use_bedrock,
        bedrock_profile=cli_profile or config.bedrock_profile,
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

    # AUTO-UPDATE: Check tool freshness before launch
    manager.ensure_tool_fresh(name, "codex")

    cmd = ["codex"]
    if not safe:
        cmd.extend(["--dangerously-bypass-approvals-and-sandbox"])
    cmd.extend(extra_args)
    mode_label = " (safe mode)" if safe else ""
    console.print(f"[bold]Launching Codex{mode_label}{bedrock_label} in {name}...[/bold]")
    manager.exec_interactive(name, cmd, extra_env=exec_env)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option("--safe", is_flag=True, default=False, help="Run without permissive flags.")
@click.option("--aws", "use_aws", is_flag=True, default=False, help="Use Amazon Bedrock.")
@click.option("--profile", "cli_profile", default=None, help="AWS profile for Bedrock auth.")
@click.pass_context
def opencode(
    ctx,
    safe,
    use_aws,
    cli_profile,
):
    """Launch opencode in the dev container."""
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    use_bedrock = use_aws

    manager, name, exec_env, config = _get_manager(
        ctx,
        bedrock=use_bedrock,
        bedrock_profile=cli_profile or config.bedrock_profile,
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

    # AUTO-UPDATE: Check tool freshness before launch
    manager.ensure_tool_fresh(name, "opencode")

    cmd = ["/root/.opencode/bin/opencode"]
    if not use_bedrock:
        # Default OpenCode to the primary coding slot (benchmark-optimized,
        # explicit Ollama tools badge). Users can switch to the secondary
        # (uncensored) slot in the OpenCode model picker at runtime.
        cmd.extend(["--model", f"ollama/{config.primary_coding_model}"])
    console.print(f"[bold]Launching opencode{bedrock_label} in {name}...[/bold]")
    manager.exec_interactive(name, cmd, extra_env=exec_env)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option("--safe", is_flag=True, default=False, help="Run without permissive flags.")
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def aider(ctx, safe, extra_args):
    """Launch aider with local LLM in the dev container."""
    manager, name, exec_env, config = _get_manager(ctx)
    aider_model = f"ollama_chat/{config.primary_coding_model}"
    cmd = ["aider", "--model", aider_model]
    if not safe:
        cmd.append("--yes-always")
    cmd.extend(["--restore-chat-history", *extra_args])
    exec_env["OLLAMA_API_BASE"] = f"http://host.docker.internal:{config.ollama_port}"

    # AUTO-UPDATE: Check tool freshness before launch
    manager.ensure_tool_fresh(name, "aider")

    mode_label = " (safe mode)" if safe else ""
    console.print(f"[bold]Launching aider{mode_label} ({aider_model}) in {name}...[/bold]")
    manager.exec_interactive(name, cmd, extra_env=exec_env)


SUPPORTED_SHELLS: dict[str, str] = {
    "bash": "/bin/bash",
    "zsh": "/usr/bin/zsh",
    "fish": "/usr/bin/fish",
}


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument(
    "shell_name",
    required=False,
    type=click.Choice(list(SUPPORTED_SHELLS.keys()), case_sensitive=False),
)
@click.pass_context
def shell(ctx, shell_name):
    """Open an interactive shell in the dev container.

    SHELL_NAME is one of bash, zsh, fish.  If omitted, an interactive
    prompt asks which shell to launch.  All three shells come pre-configured
    with modern defaults (Starship prompt, useful aliases, history tuning)
    plus Oh My Zsh for zsh and Fisher for fish.
    """
    manager, name, exec_env, _config = _get_manager(ctx)
    if not shell_name:
        shell_name = click.prompt(
            "Choose shell",
            type=click.Choice(list(SUPPORTED_SHELLS.keys()), case_sensitive=False),
            default="bash",
        )
    shell_name = shell_name.lower()
    shell_path = SUPPORTED_SHELLS[shell_name]
    console.print(f"[bold]Opening {shell_name} in {name}...[/bold]")
    manager.exec_interactive(name, [shell_path, "-l"], extra_env=exec_env)


@click.command(context_settings=CONTEXT_SETTINGS)
def init():
    """Create .ai-shell.yaml config in the current directory."""
    from ai_shell.scaffold import scaffold_project

    scaffold_project(Path.cwd())
