"""AI tool subcommands: claude, codex, opencode, aider, shell."""

import sys
from pathlib import Path

import click
from rich.console import Console

from ai_shell.config import load_config
from ai_shell.container import ContainerManager

console = Console(stderr=True)

FAST_FAILURE_THRESHOLD = 5.0  # seconds — if claude -c exits faster, retry without -c


def _get_manager(ctx) -> tuple[ContainerManager, str]:
    """Create ContainerManager from Click context and ensure dev container."""
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    manager = ContainerManager(config)
    container_name = manager.ensure_dev_container()
    return manager, container_name


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
    help="Create/overwrite .claude/ project config in current directory and exit.",
)
@click.option(
    "--clean",
    "do_clean",
    is_flag=True,
    default=False,
    help="Delete and recreate .claude/ config from templates.",
)
@click.option("--safe", is_flag=True, default=False, help="Run without permissive flags.")
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def claude(ctx, do_init, do_update, do_clean, safe, extra_args):
    """Launch Claude Code in the dev container."""
    if do_init or do_update or do_clean:
        from ai_shell.scaffold import scaffold_claude as _scaffold_claude

        _scaffold_claude(Path.cwd(), overwrite=do_update or do_clean, clean=do_clean)
        return

    manager, name = _get_manager(ctx)

    if safe:
        cmd = ["claude", *extra_args]
        console.print(f"[bold]Launching Claude Code (safe mode) in {name}...[/bold]")
        manager.exec_interactive(name, cmd)
    else:
        # Try with -c first (continue previous conversation)
        cmd_continue = ["claude", "--dangerously-skip-permissions", "-c", *extra_args]
        console.print(f"[bold]Launching Claude Code in {name}...[/bold]")
        exit_code, elapsed = manager.run_interactive(name, cmd_continue)

        if exit_code != 0 and elapsed < FAST_FAILURE_THRESHOLD:
            # -c failed quickly (likely no prior conversation), retry without it
            console.print("[yellow]No prior conversation found, starting fresh...[/yellow]")
            cmd_fresh = ["claude", "--dangerously-skip-permissions", *extra_args]
            manager.exec_interactive(name, cmd_fresh)
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
    help="Create/overwrite .codex/ and .agents/ project config in current directory and exit.",
)
@click.option(
    "--clean",
    "do_clean",
    is_flag=True,
    default=False,
    help="Delete and recreate .codex/ and .agents/ config from templates.",
)
@click.option("--safe", is_flag=True, default=False, help="Run without permissive flags.")
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def codex(ctx, do_init, do_update, do_clean, safe, extra_args):
    """Launch Codex in the dev container."""
    if do_init or do_update or do_clean:
        from ai_shell.scaffold import scaffold_codex as _scaffold_codex

        _scaffold_codex(Path.cwd(), overwrite=do_update or do_clean, clean=do_clean)
        return

    manager, name = _get_manager(ctx)
    cmd = ["codex"]
    if not safe:
        cmd.extend(["--dangerously-bypass-approvals-and-sandbox"])
    cmd.extend(["--search", *extra_args])
    console.print(f"[bold]Launching Codex{' (safe mode)' if safe else ''} in {name}...[/bold]")
    manager.exec_interactive(name, cmd)


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
    help="Create/overwrite opencode project config in current directory and exit.",
)
@click.option(
    "--clean",
    "do_clean",
    is_flag=True,
    default=False,
    help="Delete and recreate opencode and .agents/ config from templates.",
)
@click.option("--safe", is_flag=True, default=False, help="Run without permissive flags.")
@click.pass_context
def opencode(ctx, do_init, do_update, do_clean, safe):
    """Launch opencode in the dev container."""
    if do_init or do_update or do_clean:
        from ai_shell.scaffold import scaffold_opencode as _scaffold_opencode

        _scaffold_opencode(Path.cwd(), overwrite=do_update or do_clean, clean=do_clean)
        return

    manager, name = _get_manager(ctx)
    cmd = ["/root/.opencode/bin/opencode"]
    console.print(f"[bold]Launching opencode in {name}...[/bold]")
    manager.exec_interactive(name, cmd)


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
    help="Create/overwrite aider project config in current directory and exit.",
)
@click.option(
    "--clean",
    "do_clean",
    is_flag=True,
    default=False,
    help="Delete and recreate aider config from templates.",
)
@click.option("--safe", is_flag=True, default=False, help="Run without permissive flags.")
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def aider(ctx, do_init, do_update, do_clean, safe, extra_args):
    """Launch aider with local LLM in the dev container."""
    if do_init or do_update or do_clean:
        from ai_shell.scaffold import scaffold_aider as _scaffold_aider

        _scaffold_aider(Path.cwd(), overwrite=do_update or do_clean, clean=do_clean)
        return

    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    manager = ContainerManager(config)
    name = manager.ensure_dev_container()
    cmd = ["aider", "--model", config.aider_model]
    if not safe:
        cmd.append("--yes-always")
    cmd.extend(["--restore-chat-history", *extra_args])
    extra_env = {"OLLAMA_API_BASE": f"http://host.docker.internal:{config.ollama_port}"}
    mode_label = " (safe mode)" if safe else ""
    console.print(f"[bold]Launching aider{mode_label} ({config.aider_model}) in {name}...[/bold]")
    manager.exec_interactive(name, cmd, extra_env=extra_env)


@click.command()
@click.pass_context
def shell(ctx):
    """Open a bash shell in the dev container."""
    manager, name = _get_manager(ctx)
    console.print(f"[bold]Opening shell in {name}...[/bold]")
    manager.exec_interactive(name, ["/bin/bash"])


@click.command()
@click.option("--update", is_flag=True, default=False, help="Overwrite existing config files.")
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
def init(update, clean, scaffold_all):
    """Initialize ai-shell config files in the current directory."""
    from ai_shell.scaffold import scaffold_aider as _scaffold_aider
    from ai_shell.scaffold import scaffold_claude as _scaffold_claude
    from ai_shell.scaffold import scaffold_codex as _scaffold_codex
    from ai_shell.scaffold import scaffold_opencode as _scaffold_opencode
    from ai_shell.scaffold import scaffold_project

    overwrite = update or clean
    scaffold_project(Path.cwd(), overwrite=overwrite, clean=clean)
    if scaffold_all:
        _scaffold_claude(Path.cwd(), overwrite=overwrite, clean=clean)
        _scaffold_opencode(Path.cwd(), overwrite=overwrite, clean=clean)
        _scaffold_codex(Path.cwd(), overwrite=overwrite, clean=clean)
        _scaffold_aider(Path.cwd(), overwrite=overwrite, clean=clean)
