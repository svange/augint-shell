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
@click.option("--safe", is_flag=True, default=False, help="Run without permissive flags.")
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def claude(ctx, safe, extra_args):
    """Launch Claude Code in the dev container."""
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
@click.option("--safe", is_flag=True, default=False, help="Run without permissive flags.")
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def codex(ctx, safe, extra_args):
    """Launch Codex in the dev container."""
    manager, name = _get_manager(ctx)
    cmd = ["codex"]
    if not safe:
        cmd.extend(["--dangerously-bypass-approvals-and-sandbox"])
    cmd.extend(["--search", *extra_args])
    console.print(f"[bold]Launching Codex{' (safe mode)' if safe else ''} in {name}...[/bold]")
    manager.exec_interactive(name, cmd)


@click.command()
@click.option("--safe", is_flag=True, default=False, help="Run without permissive flags.")
@click.pass_context
def opencode(ctx, safe):
    """Launch opencode in the dev container."""
    manager, name = _get_manager(ctx)
    cmd = ["/root/.opencode/bin/opencode"]
    console.print(f"[bold]Launching opencode in {name}...[/bold]")
    manager.exec_interactive(name, cmd)


@click.command()
@click.option("--safe", is_flag=True, default=False, help="Run without permissive flags.")
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def aider(ctx, safe, extra_args):
    """Launch aider with local LLM in the dev container."""
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
