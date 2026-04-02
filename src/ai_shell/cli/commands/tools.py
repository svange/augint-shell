"""AI tool subcommands: claude, codex, opencode, aider, shell."""

from pathlib import Path

import click
from rich.console import Console

from ai_shell.config import load_config
from ai_shell.container import ContainerManager

console = Console(stderr=True)


def _get_manager(ctx) -> tuple[ContainerManager, str]:
    """Create ContainerManager from Click context and ensure dev container."""
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    manager = ContainerManager(config)
    container_name = manager.ensure_dev_container()
    return manager, container_name


@click.command()
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def claude(ctx, extra_args):
    """Launch Claude Code in the dev container."""
    manager, name = _get_manager(ctx)
    cmd = ["claude", *extra_args]
    console.print(f"[bold]Launching Claude Code in {name}...[/bold]")
    manager.exec_interactive(name, cmd)


@click.command("claude-x")
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def claude_x(ctx, extra_args):
    """Launch Claude Code with --dangerously-skip-permissions."""
    manager, name = _get_manager(ctx)
    cmd = ["claude", "--dangerously-skip-permissions", "-c", *extra_args]
    console.print(f"[bold]Launching Claude Code (skip-permissions) in {name}...[/bold]")
    manager.exec_interactive(name, cmd)


@click.command()
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def codex(ctx, extra_args):
    """Launch Codex in the dev container."""
    manager, name = _get_manager(ctx)
    cmd = ["codex", "--dangerously-bypass-approvals-and-sandbox", "--search", *extra_args]
    console.print(f"[bold]Launching Codex in {name}...[/bold]")
    manager.exec_interactive(name, cmd)


@click.command()
@click.pass_context
def opencode(ctx):
    """Launch opencode in the dev container."""
    manager, name = _get_manager(ctx)
    cmd = ["/root/.opencode/bin/opencode"]
    console.print(f"[bold]Launching opencode in {name}...[/bold]")
    manager.exec_interactive(name, cmd)


@click.command()
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def aider(ctx, extra_args):
    """Launch aider with local LLM in the dev container."""
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    manager = ContainerManager(config)
    name = manager.ensure_dev_container()
    cmd = [
        "aider",
        "--model",
        config.aider_model,
        "--yes-always",
        "--restore-chat-history",
        *extra_args,
    ]
    extra_env = {"OLLAMA_API_BASE": "http://host.docker.internal:11434"}
    console.print(f"[bold]Launching aider ({config.aider_model}) in {name}...[/bold]")
    manager.exec_interactive(name, cmd, extra_env=extra_env)


@click.command()
@click.pass_context
def shell(ctx):
    """Open a bash shell in the dev container."""
    manager, name = _get_manager(ctx)
    console.print(f"[bold]Opening shell in {name}...[/bold]")
    manager.exec_interactive(name, ["/bin/bash"])
