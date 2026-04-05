"""AI tool subcommands: claude, codex, opencode, aider, shell."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import click
from rich.console import Console

from ai_shell.config import load_config
from ai_shell.container import ContainerManager
from ai_shell.defaults import build_dev_environment
from ai_shell.scaffold import BranchStrategy, RepoType

console = Console(stderr=True)

FAST_FAILURE_THRESHOLD = 5.0  # seconds — if claude -c exits faster, retry without -c


# ── Repo-type resolution helpers ──────────────────────────────────


def _read_persisted_project(target_dir: Path) -> dict[str, str]:
    """Read [project] section from existing ai-shell.toml, if any."""
    try:
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
        type=click.Choice(["library", "iac", "monorepo"], case_sensitive=False),
    )
    branch_val = click.prompt(
        "Branch strategy",
        type=click.Choice(["main", "dev"], case_sensitive=False),
        default="main",
    )
    dev_branch = "dev"
    if branch_val == "dev":
        dev_branch = click.prompt("Dev branch name", default="dev")
    return RepoType(repo_type_val), BranchStrategy(branch_val), dev_branch


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
        repo_type = RepoType(flag)
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
        repo_type = RepoType(persisted["repo_type"])
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


def _get_manager(ctx) -> tuple[ContainerManager, str, dict[str, str]]:
    """Create ContainerManager from Click context and ensure dev container.

    Returns (manager, container_name, exec_env) where exec_env is a freshly
    resolved environment dict from .env / host env, suitable for passing as
    extra_env to exec/run calls so that token updates take effect immediately.
    """
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    manager = ContainerManager(config)
    container_name = manager.ensure_dev_container()
    exec_env = build_dev_environment(config.extra_env, config.project_dir)
    return manager, container_name, exec_env


@click.command()
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
@click.option("--lib", "--library", "repo_type_flag", flag_value="library", hidden=True)
@click.option("--iac", "repo_type_flag", flag_value="iac", hidden=True)
@click.option("--mono", "--monorepo", "repo_type_flag", flag_value="monorepo", hidden=True)
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def claude(
    ctx, do_init, do_update, do_reset, do_clean, safe, skip_merge, repo_type_flag, extra_args
):
    """Launch Claude Code in the dev container."""
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
        if (do_update or do_reset) and not skip_merge:
            from ai_shell.notes_merge import merge_notes_into_context

            merge_notes_into_context(Path.cwd(), "claude", background=True)
        return

    manager, name, exec_env = _get_manager(ctx)

    if safe:
        cmd = ["claude", *extra_args]
        console.print(f"[bold]Launching Claude Code (safe mode) in {name}...[/bold]")
        manager.exec_interactive(name, cmd, extra_env=exec_env)
    else:
        # Try with -c first (continue previous conversation)
        cmd_continue = ["claude", "--dangerously-skip-permissions", "-c", *extra_args]
        console.print(f"[bold]Launching Claude Code in {name}...[/bold]")
        exit_code, elapsed = manager.run_interactive(name, cmd_continue, extra_env=exec_env)

        if exit_code != 0 and elapsed < FAST_FAILURE_THRESHOLD:
            # -c failed quickly (likely no prior conversation), retry without it
            console.print("[yellow]No prior conversation found, starting fresh...[/yellow]")
            cmd_fresh = ["claude", "--dangerously-skip-permissions", *extra_args]
            manager.exec_interactive(name, cmd_fresh, extra_env=exec_env)
        else:
            sys.exit(exit_code)


@click.command()
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
@click.option("--lib", "--library", "repo_type_flag", flag_value="library", hidden=True)
@click.option("--iac", "repo_type_flag", flag_value="iac", hidden=True)
@click.option("--mono", "--monorepo", "repo_type_flag", flag_value="monorepo", hidden=True)
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def codex(
    ctx, do_init, do_update, do_reset, do_clean, safe, skip_merge, repo_type_flag, extra_args
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
        if (do_update or do_reset) and not skip_merge:
            from ai_shell.notes_merge import merge_notes_into_context

            merge_notes_into_context(Path.cwd(), "codex", background=True)
        return

    manager, name, exec_env = _get_manager(ctx)
    cmd = ["codex"]
    if not safe:
        cmd.extend(["--dangerously-bypass-approvals-and-sandbox"])
    cmd.extend(extra_args)
    console.print(f"[bold]Launching Codex{' (safe mode)' if safe else ''} in {name}...[/bold]")
    manager.exec_interactive(name, cmd, extra_env=exec_env)


@click.command()
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
@click.option("--lib", "--library", "repo_type_flag", flag_value="library", hidden=True)
@click.option("--iac", "repo_type_flag", flag_value="iac", hidden=True)
@click.option("--mono", "--monorepo", "repo_type_flag", flag_value="monorepo", hidden=True)
@click.pass_context
def opencode(ctx, do_init, do_update, do_reset, do_clean, safe, skip_merge, repo_type_flag):
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
        if (do_update or do_reset) and not skip_merge:
            from ai_shell.notes_merge import merge_notes_into_context

            merge_notes_into_context(Path.cwd(), "opencode", background=True)
        return

    manager, name, exec_env = _get_manager(ctx)
    cmd = ["/root/.opencode/bin/opencode"]
    console.print(f"[bold]Launching opencode in {name}...[/bold]")
    manager.exec_interactive(name, cmd, extra_env=exec_env)


@click.command()
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
@click.option("--iac", "repo_type_flag", flag_value="iac", hidden=True)
@click.option("--mono", "--monorepo", "repo_type_flag", flag_value="monorepo", hidden=True)
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

    manager, name, exec_env = _get_manager(ctx)
    config = manager.config
    cmd = ["aider", "--model", config.aider_model]
    if not safe:
        cmd.append("--yes-always")
    cmd.extend(["--restore-chat-history", *extra_args])
    exec_env["OLLAMA_API_BASE"] = f"http://host.docker.internal:{config.ollama_port}"
    mode_label = " (safe mode)" if safe else ""
    console.print(f"[bold]Launching aider{mode_label} ({config.aider_model}) in {name}...[/bold]")
    manager.exec_interactive(name, cmd, extra_env=exec_env)


@click.command()
@click.pass_context
def shell(ctx):
    """Open a bash shell in the dev container."""
    manager, name, exec_env = _get_manager(ctx)
    console.print(f"[bold]Opening shell in {name}...[/bold]")
    manager.exec_interactive(name, ["/bin/bash"], extra_env=exec_env)


@click.command()
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
    "--iac", "repo_type_flag", flag_value="iac", help="Scaffold for an IaC / web / backend repo."
)
@click.option(
    "--mono",
    "--monorepo",
    "repo_type_flag",
    flag_value="monorepo",
    help="Scaffold for a monorepo (git submodules).",
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
