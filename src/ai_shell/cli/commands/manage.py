"""Container management commands: status, stop, clean, logs, pull, env."""

from pathlib import Path

import click
from rich.console import Console

from ai_shell.config import load_config
from ai_shell.container import ContainerManager
from ai_shell.defaults import build_dev_environment, dev_container_name
from ai_shell.exceptions import ContainerNotFoundError

console = Console(stderr=True)


def _get_manager(ctx) -> ContainerManager:
    """Create ContainerManager from Click context."""
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    return ContainerManager(config)


@click.group("manage")
@click.pass_context
def manage_group(ctx):
    """Manage dev containers."""


@manage_group.command("status")
@click.pass_context
def manage_status(ctx):
    """Show dev container status for current project."""
    manager = _get_manager(ctx)
    name = dev_container_name(manager.config.project_name)
    status = manager.container_status(name)

    if status is None:
        console.print(
            f"[yellow]No container found for project: {manager.config.project_name}[/yellow]"
        )
    elif status == "running":
        console.print(f"[green]{name}: running[/green]")
        ports = manager.container_ports(name)
        if ports:
            console.print("  [bold]Ports:[/bold]")
            for container_port, host_addr in ports.items():
                console.print(f"    {container_port} -> {host_addr}")
    else:
        console.print(f"[yellow]{name}: {status}[/yellow]")


@manage_group.command("stop")
@click.pass_context
def manage_stop(ctx):
    """Stop the dev container for current project."""
    manager = _get_manager(ctx)
    name = dev_container_name(manager.config.project_name)

    try:
        manager.stop_container(name)
        console.print(f"[green]Stopped: {name}[/green]")
    except ContainerNotFoundError:
        console.print(f"[yellow]No container found: {name}[/yellow]")


@manage_group.command("clean")
@click.pass_context
def manage_clean(ctx):
    """Remove the dev container for current project."""
    manager = _get_manager(ctx)
    name = dev_container_name(manager.config.project_name)

    try:
        manager.remove_container(name)
        console.print(f"[green]Removed: {name}[/green]")
    except ContainerNotFoundError:
        console.print(f"[yellow]No container found: {name}[/yellow]")


@manage_group.command("logs")
@click.option("--follow", "-f", is_flag=True, help="Follow log output.")
@click.pass_context
def manage_logs(ctx, follow):
    """Tail dev container logs."""
    manager = _get_manager(ctx)
    name = dev_container_name(manager.config.project_name)

    try:
        manager.container_logs(name, follow=follow)
    except ContainerNotFoundError:
        console.print(f"[yellow]No container found: {name}[/yellow]")


@manage_group.command("pull")
@click.pass_context
def manage_pull(ctx):
    """Pull the latest Docker image."""
    manager = _get_manager(ctx)
    image = manager.config.full_image
    console.print(f"[bold]Pulling {image}...[/bold]")
    manager._pull_image_if_needed(image)
    console.print(f"[green]Image ready: {image}[/green]")


@manage_group.command("env")
@click.option("--aws", "use_aws", is_flag=True, default=False, help="Show Bedrock environment.")
@click.pass_context
def manage_env(ctx, use_aws):
    """Show environment variables that would be passed to AI tool processes."""
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    use_bedrock = use_aws or config.claude_provider == "aws"

    exec_env = build_dev_environment(
        config.extra_env,
        config.project_dir,
        bedrock=use_bedrock,
        aws_profile=config.ai_profile,
        aws_region=config.aws_region,
        bedrock_profile=config.bedrock_profile if use_bedrock else "",
    )

    console.print("[bold]Resolved exec environment:[/bold]")
    for key in sorted(exec_env):
        value = exec_env[key]
        if key in ("GH_TOKEN", "GITHUB_TOKEN") and value:
            value = value[:4] + "..." + value[-4:] if len(value) > 8 else "***"
        console.print(f"  {key}={value}")
