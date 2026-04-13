"""AI tool subcommands: claude, codex, opencode, aider, shell."""

from __future__ import annotations

import logging
import subprocess
import sys
import tomllib
import uuid
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from ai_shell.cli import CONTEXT_SETTINGS
from ai_shell.config import AiShellConfig, load_config
from ai_shell.container import ContainerManager
from ai_shell.defaults import build_dev_environment, dev_container_name
from ai_shell.scaffold import BranchStrategy, RepoType

logger = logging.getLogger(__name__)
console = Console(stderr=True)

FAST_FAILURE_THRESHOLD = 5.0  # seconds — if claude -c exits faster, retry without -c

# Worktrees are created inside .claude/worktrees/ so they stay within the bind
# mount and remain visible on the host.  The branch name mirrors the directory
# name with a "worktree-" prefix, matching the convention used by ``claude
# --worktree``.
WORKTREE_BASE_DIR = ".claude/worktrees"


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


def _inject_codex_api_key(container_name: str, api_key: str) -> None:
    """Write the configured API key into ~/.codex/auth.json inside the container.

    Codex reads credentials from auth.json rather than the OPENAI_API_KEY env var,
    so the env var alone has no effect. This patches auth.json in-place before
    launch. Because ~/.codex/ is bind-mounted from the host, this also updates
    the host file — effectively switching the active OpenAI account.

    The key is passed via a dedicated env var to avoid any shell-escaping issues.
    """
    # Use python3 inside the container: read OPENAI_API_KEY from env and write to auth.json.
    # auth_mode is set to "apikey" to tell codex not to use SSO tokens.
    python_cmd = (
        "import json, os; "
        "p = os.path.expanduser('~/.codex/auth.json'); "
        "d = json.loads(open(p).read()) if os.path.exists(p) else {}; "
        "d['auth_mode'] = 'apikey'; "
        "d['OPENAI_API_KEY'] = os.environ['_CODEX_INJECT_KEY']; "
        "open(p, 'w').write(json.dumps(d))"
    )
    args = [
        "docker",
        "exec",
        "-e",
        f"_CODEX_INJECT_KEY={api_key}",
        container_name,
        "python3",
        "-c",
        python_cmd,
    ]
    logger.debug("codex api key inject: docker exec %s python3 -c ...", container_name)
    result = subprocess.run(args, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise click.ClickException(
            f"Failed to inject codex api_key into ~/.codex/auth.json:\n  {result.stderr.strip()}"
        )


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


# ── Repo-type resolution helpers ──────────────────────────────────


def _read_persisted_project(target_dir: Path) -> dict[str, str]:
    """Read [project] section from existing .ai-shell.toml, if any."""
    try:
        toml_path = target_dir / ".ai-shell.toml"
        if not toml_path.exists():
            toml_path = target_dir / "ai-shell.toml"
        if not toml_path.exists():
            return {}
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        result: dict[str, str] = data.get("project", {})
        return result
    except (OSError, tomllib.TOMLDecodeError, TypeError):
        return {}


def _prompt_repo_config() -> tuple[RepoType, BranchStrategy, str]:
    """Interactively ask user for repo type and branch strategy."""
    repo_type_val = click.prompt(
        "Repo type",
        type=click.Choice(["library", "service", "workspace"], case_sensitive=False),
    )
    branch_val = click.prompt(
        "Branch strategy",
        type=click.Choice(["main", "dev"], case_sensitive=False),
        default="main",
    )
    dev_branch = "dev"
    if branch_val == "dev":
        dev_branch = click.prompt("Dev branch name", default="dev")
    return _normalize_repo_type_value(repo_type_val), BranchStrategy(branch_val), dev_branch


def _normalize_repo_type_value(value: str) -> RepoType:
    """Map user-facing aliases onto the internal repo type enum."""
    if value == "iac":
        return RepoType.SERVICE
    return RepoType(value)


def _resolve_repo_config(
    flag: str | None,
    target_dir: Path,
    *,
    prompt_if_missing: bool = False,
) -> tuple[RepoType | None, BranchStrategy | None, str]:
    """Resolve repo type / branch strategy from flag, config, or prompt.

    Returns (repo_type, branch_strategy, dev_branch).
    """
    # 1. CLI flag wins
    if flag:
        repo_type = _normalize_repo_type_value(flag)
        # When flag is given without existing config, prompt for branch strategy
        persisted = _read_persisted_project(target_dir)
        if "branch_strategy" in persisted:
            branch_strategy = BranchStrategy(persisted["branch_strategy"])
            dev_branch = persisted.get("dev_branch", "dev")
        elif prompt_if_missing:
            branch_val = click.prompt(
                "Branch strategy",
                type=click.Choice(["main", "dev"], case_sensitive=False),
                default="main",
            )
            branch_strategy = BranchStrategy(branch_val)
            dev_branch = "dev"
            if branch_strategy == BranchStrategy.DEV:
                dev_branch = click.prompt("Dev branch name", default="dev")
        else:
            branch_strategy = None
            dev_branch = "dev"
        return repo_type, branch_strategy, dev_branch

    # 2. Existing ai-shell.toml [project] section
    persisted = _read_persisted_project(target_dir)
    if "repo_type" in persisted:
        repo_type = _normalize_repo_type_value(persisted["repo_type"])
        branch_strategy = (
            BranchStrategy(persisted["branch_strategy"]) if "branch_strategy" in persisted else None
        )
        dev_branch = persisted.get("dev_branch", "dev")
        return repo_type, branch_strategy, dev_branch

    # 3. Interactive prompt (only for init, not for update/reset without flag)
    if prompt_if_missing:
        return _prompt_repo_config()

    # 4. No config available
    return None, None, "dev"


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
    manager = ContainerManager(config)
    container_name = manager.ensure_dev_container()
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


def _launch_multi(
    ctx: click.Context,
    *,
    safe: bool,
    use_aws: bool,
    cli_profile: str | None,
    skip_preflight: bool,
    extra_args: tuple[str, ...],
) -> None:
    """Workspace multi-pane Claude launcher.

    Validates workspace.yaml, presents an interactive selector, then launches
    a tmux session inside the dev container with one pane per selected repo.
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

    workspace_yaml = Path.cwd() / "workspace.yaml"
    if not workspace_yaml.exists():
        raise click.ClickException("No workspace.yaml found. --multi requires a workspace repo.")

    workspace_name, repos = _load_workspace_repos(workspace_yaml)

    # Check for existing tmux session before presenting the selector.
    # The container and session might still be running from a previous
    # invocation (e.g. after the user detached with C-b d or closed
    # the terminal).
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    session_name = f"{TMUX_SESSION_PREFIX}-{config.project_name}"
    container_name = dev_container_name(config.project_name, config.project_dir)

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
            sys.stdout.flush()
            sys.stderr.flush()
            attach = subprocess.run(attach_cmd)
            sys.exit(attach.returncode)
        elif choice == "cancel":
            return
        # choice == "fresh": fall through to selector and recreate

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
        # Re-derive config from the selected repo's directory
        project = ctx.obj.get("project") if ctx.obj else None
        config = load_config(project_override=project, project_dir=sel_path)
        use_bedrock = use_aws or config.claude_provider == "aws"
        manager = ContainerManager(config)
        container_name = manager.ensure_dev_container()
        exec_env = build_dev_environment(
            config.extra_env,
            config.project_dir,
            project_name=config.project_name,
            bedrock=use_bedrock,
            aws_profile=config.ai_profile,
            aws_region=config.aws_region,
            bedrock_profile=cli_profile or config.bedrock_profile,
        )

        if use_bedrock and not skip_preflight:
            _check_bedrock_access(container_name, exec_env)

        workdir = f"/root/projects/{config.project_name}"
        if safe:
            cmd = ["claude", *extra_args]
            manager.exec_interactive(container_name, cmd, extra_env=exec_env, workdir=workdir)
        else:
            cmd_c = ["claude", "--dangerously-skip-permissions", "-c", *extra_args]
            exit_code, elapsed = manager.run_interactive(
                container_name, cmd_c, extra_env=exec_env, workdir=workdir
            )
            if exit_code != 0 and elapsed < FAST_FAILURE_THRESHOLD:
                cmd_fresh = ["claude", "--dangerously-skip-permissions", *extra_args]
                manager.exec_interactive(
                    container_name, cmd_fresh, extra_env=exec_env, workdir=workdir
                )
            else:
                sys.exit(exit_code)
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
    exec_env = build_dev_environment(
        config.extra_env,
        config.project_dir,
        project_name=config.project_name,
        bedrock=use_bedrock,
        aws_profile=config.ai_profile,
        aws_region=config.aws_region,
        bedrock_profile=cli_profile or config.bedrock_profile,
    )

    if use_bedrock and not skip_preflight:
        _check_bedrock_access(container_name, exec_env)

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

        pane_cmd = build_claude_pane_command(
            repo_name=repo_name,
            safe=safe,
            extra_args=extra_args,
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
    sys.stdout.flush()
    sys.stderr.flush()
    attach = subprocess.run(final_cmd)
    sys.exit(attach.returncode)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--init",
    "do_init",
    is_flag=True,
    default=False,
    help="Create .claude/ project config in current directory and exit.",
)
@click.option(
    "--update",
    "do_update",
    is_flag=True,
    default=False,
    help="Update managed files, merging settings to preserve user customizations.",
)
@click.option(
    "--reset",
    "do_reset",
    is_flag=True,
    default=False,
    help="Force-overwrite all managed config files from templates.",
)
@click.option(
    "--clean",
    "do_clean",
    is_flag=True,
    default=False,
    help="Delete and recreate .claude/ config from templates.",
)
@click.option("--safe", is_flag=True, default=False, help="Run without permissive flags.")
@click.option(
    "--no-merge",
    "skip_merge",
    is_flag=True,
    default=False,
    help="Skip merging notes into context file on --update/--reset.",
)
@click.option("--aws", "use_aws", is_flag=True, default=False, help="Use Amazon Bedrock.")
@click.option("--profile", "cli_profile", default=None, help="AWS profile for Bedrock auth.")
@click.option(
    "--no-preflight",
    "skip_preflight",
    is_flag=True,
    default=False,
    help="Skip Bedrock pre-flight check (for debugging).",
)
@click.option("--lib", "--library", "repo_type_flag", flag_value="library", hidden=True)
@click.option("--service", "repo_type_flag", flag_value="service", hidden=True)
@click.option("--workspace", "repo_type_flag", flag_value="workspace", hidden=True)
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
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def claude(
    ctx,
    do_init,
    do_update,
    do_reset,
    do_clean,
    safe,
    skip_merge,
    use_aws,
    cli_profile,
    skip_preflight,
    repo_type_flag,
    worktree_name,
    do_multi,
    extra_args,
):
    """Launch Claude Code in the dev container."""
    # Incompatibility check: --multi cannot combine with scaffold or worktree flags
    if do_multi and any([do_init, do_update, do_reset, do_clean]):
        raise click.ClickException("--multi is incompatible with --init/--update/--reset/--clean.")
    if do_multi and worktree_name is not None:
        raise click.ClickException("--multi is incompatible with --worktree.")

    if do_init or do_update or do_reset or do_clean:
        from ai_shell.scaffold import scaffold_claude as _scaffold_claude

        target_dir = Path.cwd()
        repo_type, branch_strategy, _dev = _resolve_repo_config(
            repo_type_flag,
            target_dir,
        )
        _scaffold_claude(
            target_dir,
            overwrite=do_reset or do_clean,
            clean=do_clean,
            merge=do_update,
            repo_type=repo_type,
            branch_strategy=branch_strategy,
        )
        if (do_init or do_update or do_reset) and not skip_merge:
            from ai_shell.notes_merge import merge_notes_into_context

            merge_notes_into_context(Path.cwd(), "claude", background=True)
        return

    if do_multi:
        _launch_multi(
            ctx,
            safe=safe,
            use_aws=use_aws,
            cli_profile=cli_profile,
            skip_preflight=skip_preflight,
            extra_args=extra_args,
        )
        return

    # Auto-init if .claude/ is missing
    if not (Path.cwd() / ".claude").exists():
        console.print("[dim].claude/ not found - running first-time init...[/dim]")
        from ai_shell.scaffold import scaffold_claude as _scaffold_claude

        _auto_repo_type, _auto_branch, _auto_dev = _resolve_repo_config(None, Path.cwd())
        _scaffold_claude(
            Path.cwd(),
            repo_type=_auto_repo_type,
            branch_strategy=_auto_branch,
        )
        if not skip_merge:
            from ai_shell.notes_merge import merge_notes_into_context

            merge_notes_into_context(Path.cwd(), "claude", background=True)

    # Load config first to check provider setting
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    use_bedrock = use_aws or config.claude_provider == "aws"

    manager, name, exec_env, config = _get_manager(
        ctx,
        bedrock=use_bedrock,
        bedrock_profile=cli_profile or "",
    )

    if use_bedrock:
        profile_label = exec_env.get("AWS_PROFILE", "default")
        region_label = exec_env.get("AWS_REGION", "us-east-1")
        bedrock_label = f" via Bedrock (profile={profile_label}, region={region_label})"
        if not skip_preflight:
            console.print(
                f"Checking Bedrock access (profile={profile_label}, region={region_label})..."
            )
            _check_bedrock_access(name, exec_env)
    else:
        bedrock_label = ""

    # Resolve worktree working directory (if --worktree/-w was given)
    worktree_dir: str | None = None
    if worktree_name is not None:
        if worktree_name == "":
            worktree_name = _generate_worktree_name()
        container_project_dir = f"/root/projects/{config.project_name}"
        worktree_dir = _setup_worktree(name, container_project_dir, worktree_name)
        console.print(f"[dim]Worktree: {worktree_dir} (branch: worktree-{worktree_name})[/dim]")

    if safe:
        cmd = ["claude", *extra_args]
        console.print(f"[bold]Launching Claude Code (safe mode){bedrock_label} in {name}...[/bold]")
        manager.exec_interactive(name, cmd, extra_env=exec_env, workdir=worktree_dir)
    else:
        # Try with -c first (continue previous conversation)
        cmd_continue = ["claude", "--dangerously-skip-permissions", "-c", *extra_args]
        console.print(f"[bold]Launching Claude Code{bedrock_label} in {name}...[/bold]")
        exit_code, elapsed = manager.run_interactive(
            name, cmd_continue, extra_env=exec_env, workdir=worktree_dir
        )

        if exit_code != 0 and elapsed < FAST_FAILURE_THRESHOLD:
            # -c failed quickly (likely no prior conversation), retry without it
            console.print("[yellow]No prior conversation found, starting fresh...[/yellow]")
            cmd_fresh = ["claude", "--dangerously-skip-permissions", *extra_args]
            manager.exec_interactive(name, cmd_fresh, extra_env=exec_env, workdir=worktree_dir)
        else:
            sys.exit(exit_code)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--init",
    "do_init",
    is_flag=True,
    default=False,
    help="Create .codex/ and .agents/ project config in current directory and exit.",
)
@click.option(
    "--update",
    "do_update",
    is_flag=True,
    default=False,
    help="Update managed files, merging settings to preserve user customizations.",
)
@click.option(
    "--reset",
    "do_reset",
    is_flag=True,
    default=False,
    help="Force-overwrite all managed config files from templates.",
)
@click.option(
    "--clean",
    "do_clean",
    is_flag=True,
    default=False,
    help="Delete and recreate .codex/ and .agents/ config from templates.",
)
@click.option("--safe", is_flag=True, default=False, help="Run without permissive flags.")
@click.option(
    "--no-merge",
    "skip_merge",
    is_flag=True,
    default=False,
    help="Skip merging notes into context file on --update/--reset.",
)
@click.option("--aws", "use_aws", is_flag=True, default=False, help="Use Amazon Bedrock.")
@click.option("--profile", "cli_profile", default=None, help="AWS profile for Bedrock auth.")
@click.option(
    "--no-preflight",
    "skip_preflight",
    is_flag=True,
    default=False,
    help="Skip Bedrock pre-flight check (for debugging).",
)
@click.option("--lib", "--library", "repo_type_flag", flag_value="library", hidden=True)
@click.option("--service", "repo_type_flag", flag_value="service", hidden=True)
@click.option("--workspace", "repo_type_flag", flag_value="workspace", hidden=True)
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def codex(
    ctx,
    do_init,
    do_update,
    do_reset,
    do_clean,
    safe,
    skip_merge,
    use_aws,
    cli_profile,
    skip_preflight,
    repo_type_flag,
    extra_args,
):
    """Launch Codex in the dev container."""
    if do_init or do_update or do_reset or do_clean:
        from ai_shell.scaffold import scaffold_codex as _scaffold_codex

        target_dir = Path.cwd()
        repo_type, branch_strategy, _dev = _resolve_repo_config(
            repo_type_flag,
            target_dir,
        )
        _scaffold_codex(
            target_dir,
            overwrite=do_reset or do_clean,
            clean=do_clean,
            merge=do_update,
            repo_type=repo_type,
            branch_strategy=branch_strategy,
        )
        if (do_init or do_update or do_reset) and not skip_merge:
            from ai_shell.notes_merge import merge_notes_into_context

            merge_notes_into_context(Path.cwd(), "codex", background=True)
        return

    # Auto-init if .codex/ is missing
    if not (Path.cwd() / ".codex").exists():
        console.print("[dim].codex/ not found - running first-time init...[/dim]")
        from ai_shell.scaffold import scaffold_codex as _scaffold_codex

        _auto_repo_type, _auto_branch, _auto_dev = _resolve_repo_config(None, Path.cwd())
        _scaffold_codex(
            Path.cwd(),
            repo_type=_auto_repo_type,
            branch_strategy=_auto_branch,
        )
        if not skip_merge:
            from ai_shell.notes_merge import merge_notes_into_context

            merge_notes_into_context(Path.cwd(), "codex", background=True)

    # Load config first to check provider setting
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    use_bedrock = use_aws or config.codex_provider == "aws"

    manager, name, exec_env, config = _get_manager(
        ctx,
        bedrock=use_bedrock,
        bedrock_profile=cli_profile or config.codex_profile,
    )

    # Inject API key into ~/.codex/auth.json if configured.
    # Codex reads auth from auth.json (not the OPENAI_API_KEY env var), so we patch
    # auth.json directly. This also updates the bind-mounted host file, effectively
    # switching the active OpenAI account for the duration of the session.
    if config.codex_openai_api_key:
        _inject_codex_api_key(name, config.codex_openai_api_key)

    if use_bedrock:
        profile_label = exec_env.get("AWS_PROFILE", "default")
        region_label = exec_env.get("AWS_REGION", "us-east-1")
        bedrock_label = f" via Bedrock (profile={profile_label}, region={region_label})"
        if not skip_preflight:
            console.print(
                f"Checking Bedrock access (profile={profile_label}, region={region_label})..."
            )
            _check_bedrock_access(name, exec_env)
    else:
        bedrock_label = ""

    cmd = ["codex"]
    if not safe:
        cmd.extend(["--dangerously-bypass-approvals-and-sandbox"])
    cmd.extend(extra_args)
    mode_label = " (safe mode)" if safe else ""
    console.print(f"[bold]Launching Codex{mode_label}{bedrock_label} in {name}...[/bold]")
    manager.exec_interactive(name, cmd, extra_env=exec_env)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--init",
    "do_init",
    is_flag=True,
    default=False,
    help="Create opencode project config in current directory and exit.",
)
@click.option(
    "--update",
    "do_update",
    is_flag=True,
    default=False,
    help="Update managed files, merging settings to preserve user customizations.",
)
@click.option(
    "--reset",
    "do_reset",
    is_flag=True,
    default=False,
    help="Force-overwrite all managed config files from templates.",
)
@click.option(
    "--clean",
    "do_clean",
    is_flag=True,
    default=False,
    help="Delete and recreate opencode and .agents/ config from templates.",
)
@click.option("--safe", is_flag=True, default=False, help="Run without permissive flags.")
@click.option(
    "--no-merge",
    "skip_merge",
    is_flag=True,
    default=False,
    help="Skip merging notes into context file on --update/--reset.",
)
@click.option("--aws", "use_aws", is_flag=True, default=False, help="Use Amazon Bedrock.")
@click.option("--profile", "cli_profile", default=None, help="AWS profile for Bedrock auth.")
@click.option(
    "--no-preflight",
    "skip_preflight",
    is_flag=True,
    default=False,
    help="Skip Bedrock pre-flight check (for debugging).",
)
@click.option("--lib", "--library", "repo_type_flag", flag_value="library", hidden=True)
@click.option("--service", "repo_type_flag", flag_value="service", hidden=True)
@click.option("--workspace", "repo_type_flag", flag_value="workspace", hidden=True)
@click.pass_context
def opencode(
    ctx,
    do_init,
    do_update,
    do_reset,
    do_clean,
    safe,
    skip_merge,
    use_aws,
    cli_profile,
    skip_preflight,
    repo_type_flag,
):
    """Launch opencode in the dev container."""
    if do_init or do_update or do_reset or do_clean:
        from ai_shell.scaffold import scaffold_opencode as _scaffold_opencode

        target_dir = Path.cwd()
        repo_type, branch_strategy, _dev = _resolve_repo_config(
            repo_type_flag,
            target_dir,
        )
        _scaffold_opencode(
            target_dir,
            overwrite=do_reset or do_clean,
            clean=do_clean,
            merge=do_update,
            repo_type=repo_type,
            branch_strategy=branch_strategy,
        )
        if (do_init or do_update or do_reset) and not skip_merge:
            from ai_shell.notes_merge import merge_notes_into_context

            merge_notes_into_context(Path.cwd(), "opencode", background=True)
        return

    # Auto-init if opencode.json is missing
    if not (Path.cwd() / "opencode.json").exists():
        console.print("[dim]opencode.json not found - running first-time init...[/dim]")
        from ai_shell.scaffold import scaffold_opencode as _scaffold_opencode

        _auto_repo_type, _auto_branch, _auto_dev = _resolve_repo_config(None, Path.cwd())
        _scaffold_opencode(
            Path.cwd(),
            repo_type=_auto_repo_type,
            branch_strategy=_auto_branch,
        )
        if not skip_merge:
            from ai_shell.notes_merge import merge_notes_into_context

            merge_notes_into_context(Path.cwd(), "opencode", background=True)

    # Load config first to check provider setting
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    use_bedrock = use_aws or config.opencode_provider == "aws"

    manager, name, exec_env, config = _get_manager(
        ctx,
        bedrock=use_bedrock,
        bedrock_profile=cli_profile or "",
    )

    if use_bedrock:
        profile_label = exec_env.get("AWS_PROFILE", "default")
        region_label = exec_env.get("AWS_REGION", "us-east-1")
        bedrock_label = f" via Bedrock (profile={profile_label}, region={region_label})"
        if not skip_preflight:
            console.print(
                f"Checking Bedrock access (profile={profile_label}, region={region_label})..."
            )
            _check_bedrock_access(name, exec_env)
    else:
        bedrock_label = ""

    cmd = ["/root/.opencode/bin/opencode"]
    console.print(f"[bold]Launching opencode{bedrock_label} in {name}...[/bold]")
    manager.exec_interactive(name, cmd, extra_env=exec_env)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--init",
    "do_init",
    is_flag=True,
    default=False,
    help="Create aider project config in current directory and exit.",
)
@click.option(
    "--update",
    "do_update",
    is_flag=True,
    default=False,
    help="Update managed files, merging settings to preserve user customizations.",
)
@click.option(
    "--reset",
    "do_reset",
    is_flag=True,
    default=False,
    help="Force-overwrite all managed config files from templates.",
)
@click.option(
    "--clean",
    "do_clean",
    is_flag=True,
    default=False,
    help="Delete and recreate aider config from templates.",
)
@click.option("--safe", is_flag=True, default=False, help="Run without permissive flags.")
@click.option("--lib", "--library", "repo_type_flag", flag_value="library", hidden=True)
@click.option("--service", "repo_type_flag", flag_value="service", hidden=True)
@click.option("--workspace", "repo_type_flag", flag_value="workspace", hidden=True)
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def aider(ctx, do_init, do_update, do_reset, do_clean, safe, repo_type_flag, extra_args):
    """Launch aider with local LLM in the dev container."""
    if do_init or do_update or do_reset or do_clean:
        from ai_shell.scaffold import scaffold_aider as _scaffold_aider

        target_dir = Path.cwd()
        repo_type, _branch, _dev = _resolve_repo_config(
            repo_type_flag,
            target_dir,
        )
        _scaffold_aider(
            target_dir,
            overwrite=do_reset or do_clean,
            clean=do_clean,
            merge=do_update,
            repo_type=repo_type,
        )
        return

    # Auto-init if .aider.conf.yml is missing
    if not (Path.cwd() / ".aider.conf.yml").exists():
        console.print("[dim].aider.conf.yml not found - running first-time init...[/dim]")
        from ai_shell.scaffold import scaffold_aider as _scaffold_aider

        _auto_repo_type, _auto_branch, _auto_dev = _resolve_repo_config(None, Path.cwd())
        _scaffold_aider(
            Path.cwd(),
            repo_type=_auto_repo_type,
        )

    manager, name, exec_env, config = _get_manager(ctx)
    cmd = ["aider", "--model", config.aider_model]
    if not safe:
        cmd.append("--yes-always")
    cmd.extend(["--restore-chat-history", *extra_args])
    exec_env["OLLAMA_API_BASE"] = f"http://host.docker.internal:{config.ollama_port}"
    mode_label = " (safe mode)" if safe else ""
    console.print(f"[bold]Launching aider{mode_label} ({config.aider_model}) in {name}...[/bold]")
    manager.exec_interactive(name, cmd, extra_env=exec_env)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.pass_context
def shell(ctx):
    """Open a bash shell in the dev container."""
    manager, name, exec_env, _config = _get_manager(ctx)
    console.print(f"[bold]Opening shell in {name}...[/bold]")
    manager.exec_interactive(name, ["/bin/bash"], extra_env=exec_env)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--update",
    is_flag=True,
    default=False,
    help="Update managed files, merging settings to preserve user customizations.",
)
@click.option(
    "--reset",
    is_flag=True,
    default=False,
    help="Force-overwrite all managed config files from templates.",
)
@click.option(
    "--clean",
    is_flag=True,
    default=False,
    help="Delete and recreate all config from templates.",
)
@click.option(
    "--all",
    "scaffold_all",
    is_flag=True,
    default=False,
    help="Also scaffold all tool configs (claude, codex, opencode, aider).",
)
@click.option(
    "--no-merge",
    "skip_merge",
    is_flag=True,
    default=False,
    help="Skip merging notes into context files on --update/--reset --all.",
)
@click.option(
    "--lib",
    "--library",
    "repo_type_flag",
    flag_value="library",
    help="Scaffold for a library repo (publishes packages).",
)
@click.option(
    "--service",
    "repo_type_flag",
    flag_value="service",
    help="Scaffold for a service / web / backend repo.",
)
@click.option(
    "--workspace",
    "repo_type_flag",
    flag_value="workspace",
    help="Scaffold for a workspace repo coordinating multiple child repos.",
)
def init(update, reset, clean, scaffold_all, skip_merge, repo_type_flag):
    """Initialize ai-shell config files in the current directory."""
    from ai_shell.scaffold import scaffold_aider as _scaffold_aider
    from ai_shell.scaffold import scaffold_claude as _scaffold_claude
    from ai_shell.scaffold import scaffold_codex as _scaffold_codex
    from ai_shell.scaffold import scaffold_opencode as _scaffold_opencode
    from ai_shell.scaffold import scaffold_project

    overwrite = reset or clean
    merge = update
    target_dir = Path.cwd()

    # Resolve repo type: flag > persisted config > interactive prompt
    # Prompt only on fresh init (not update/reset without explicit flag)
    is_fresh_init = not (update or reset or clean)
    repo_type, branch_strategy, dev_branch = _resolve_repo_config(
        repo_type_flag,
        target_dir,
        prompt_if_missing=is_fresh_init,
    )

    scaffold_project(
        target_dir,
        overwrite=overwrite,
        clean=clean,
        merge=merge,
        repo_type=repo_type,
        branch_strategy=branch_strategy,
        dev_branch=dev_branch,
    )
    if scaffold_all:
        _scaffold_claude(
            target_dir,
            overwrite=overwrite,
            clean=clean,
            merge=merge,
            repo_type=repo_type,
            branch_strategy=branch_strategy,
        )
        _scaffold_opencode(
            target_dir,
            overwrite=overwrite,
            clean=clean,
            merge=merge,
            repo_type=repo_type,
            branch_strategy=branch_strategy,
        )
        _scaffold_codex(
            target_dir,
            overwrite=overwrite,
            clean=clean,
            merge=merge,
            repo_type=repo_type,
            branch_strategy=branch_strategy,
        )
        _scaffold_aider(
            target_dir,
            overwrite=overwrite,
            clean=clean,
            merge=merge,
            repo_type=repo_type,
        )
        if (update or reset) and not skip_merge:
            from ai_shell.notes_merge import merge_notes_into_context

            merge_notes_into_context(target_dir, "claude", background=True)
            merge_notes_into_context(target_dir, "codex", background=True)
