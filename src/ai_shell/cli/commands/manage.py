"""Container management commands: status, list, stop, clean, logs, pull, env, and doctor."""

from pathlib import Path

import click
from rich.console import Console

from ai_shell.cli import CONTEXT_SETTINGS
from ai_shell.config import load_config
from ai_shell.container import ContainerManager
from ai_shell.defaults import _find_gh_config_dir, build_dev_environment
from ai_shell.exceptions import ContainerNotFoundError, DockerNotAvailableError
from ai_shell.gpu import detect_gpu
from ai_shell.local_chrome import find_chrome

console = Console(stderr=True)


def _get_manager(ctx) -> ContainerManager:
    """Create ContainerManager from Click context."""
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    return ContainerManager(config)


@click.group("manage", context_settings=CONTEXT_SETTINGS)
@click.pass_context
def manage_group(ctx):
    """Manage dev containers."""


@manage_group.command("status")
@click.pass_context
def manage_status(ctx):
    """Show dev container status for current project."""
    manager = _get_manager(ctx)
    name, _ = manager.resolve_dev_container()
    status = manager.container_status(name)

    if status is None:
        console.print(
            f"[yellow]No container found for project: {manager.config.project_name}[/yellow]"
        )
    elif status == "running":
        console.print(f"[green]{name}: running[/green]")
        ports = manager.container_ports(name)
        if ports:
            console.print("\n  [bold]Dev server URLs:[/bold]")
            for container_port, host_addr in ports.items():
                host_port = host_addr.rsplit(":", 1)[-1]
                label = container_port.split("/")[0]
                console.print(
                    f"    [cyan]http://localhost:{host_port}[/cyan]  [dim italic]({label})[/dim italic]"
                )
    else:
        console.print(f"[yellow]{name}: {status}[/yellow]")


@manage_group.command("list")
@click.pass_context
def manage_list(ctx):
    """List all ai-shell dev containers on this host."""
    manager = _get_manager(ctx)
    items = manager.list_dev_containers()
    if not items:
        console.print("[dim]No dev containers found.[/dim]")
        return

    console.print("[bold]Dev containers:[/bold]")
    for item in items:
        name = item["name"]
        status = item["status"]
        project_dir = item.get("project_dir") or ""
        color = "green" if status == "running" else "yellow"
        suffix = f" [dim]({project_dir})[/dim]" if project_dir else ""
        console.print(f"  [{color}]{name}: {status}[/{color}]{suffix}")


@manage_group.command("stop")
@click.pass_context
def manage_stop(ctx):
    """Stop the dev container for current project."""
    manager = _get_manager(ctx)
    name, _ = manager.resolve_dev_container()

    try:
        manager.stop_container(name)
        console.print(f"[green]Stopped: {name}[/green]")
    except ContainerNotFoundError:
        console.print(f"[yellow]No container found: {name}[/yellow]")


@manage_group.command("clean")
@click.pass_context
def manage_clean(ctx):
    """Remove the dev container and per-project volumes for current project."""
    manager = _get_manager(ctx)
    name, _ = manager.resolve_dev_container()

    try:
        manager.remove_container(name)
        console.print(f"[green]Removed: {name}[/green]")
    except ContainerNotFoundError:
        console.print(f"[yellow]No container found: {name}[/yellow]")

    removed_vols = manager.remove_project_volumes()
    if isinstance(removed_vols, list):
        for vol in removed_vols:
            console.print(f"[green]Removed volume: {vol}[/green]")


@manage_group.command("logs")
@click.option("--follow", "-f", is_flag=True, help="Follow log output.")
@click.pass_context
def manage_logs(ctx, follow):
    """Tail dev container logs."""
    manager = _get_manager(ctx)
    name, _ = manager.resolve_dev_container()

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
    manager._pull_image_if_needed(image, force=True)
    console.print(f"[green]Image ready: {image}[/green]")


@manage_group.command("env")
@click.option("--aws", "use_aws", is_flag=True, default=False, help="Show Bedrock environment.")
@click.option(
    "--env",
    "env_file",
    is_flag=False,
    flag_value=".env",
    default=None,
    help="Load .env into the container (all variables). Defaults to ./.env when flag given without value.",
)
@click.pass_context
def manage_env(ctx, use_aws, env_file):
    """Show environment variables that would be passed to AI tool processes."""
    resolved_env = Path(env_file) if env_file else None
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
        env_file=resolved_env,
        github_auth=config.github_auth,
    )

    console.print("[bold]Resolved exec environment:[/bold]")
    for key in sorted(exec_env):
        value = exec_env[key]
        if key in ("GH_TOKEN", "GITHUB_TOKEN") and value:
            value = value[:4] + "..." + value[-4:] if len(value) > 8 else "***"
        console.print(f"  {key}={value}")


@click.command("doctor", context_settings=CONTEXT_SETTINGS)
@click.pass_context
def doctor(ctx):
    """Run host preflight diagnostics for ai-shell."""
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    console.print("[bold]ai-shell doctor[/bold]")

    # 1. Docker daemon
    try:
        manager = ContainerManager(config)
        console.print("  [green]✓[/green] Docker daemon reachable")
    except DockerNotAvailableError as exc:
        console.print(f"  [red]✗[/red] Docker daemon unreachable: {exc}")
        manager = None

    # 2. Dev image cached locally
    if manager is not None:
        try:
            manager.client.images.get(config.full_image)
            console.print(f"  [green]✓[/green] Dev image cached: {config.full_image}")
        except Exception:
            console.print(
                f"  [yellow]![/yellow] Dev image not yet pulled: {config.full_image} "
                "[dim](will pull on first launch or via 'ai-shell manage pull')[/dim]"
            )

    # 3. Host Chrome
    chrome_path = find_chrome()
    if chrome_path:
        console.print(f"  [green]✓[/green] Host Chrome: {chrome_path}")
    else:
        console.print(
            "  [yellow]![/yellow] Host Chrome not found [dim](optional; needed for --local-chrome)[/dim]"
        )

    # 4. Credentials & config
    augint_env = Path.home() / ".augint" / ".env"
    if augint_env.is_file():
        console.print(f"  [green]✓[/green] Global credentials: {augint_env}")
    else:
        console.print(f"  [dim]-[/dim] Global credentials not found at {augint_env}")

    gh_dir = _find_gh_config_dir()
    if gh_dir is not None:
        console.print(f"  [green]✓[/green] GitHub CLI config: {gh_dir}")
    else:
        console.print("  [dim]-[/dim] GitHub CLI config (~/.config/gh) not found on host")

    # 5. GPU
    if detect_gpu():
        console.print("  [green]✓[/green] NVIDIA GPU detected")
    else:
        console.print(
            "  [dim]-[/dim] No NVIDIA GPU detected [dim](optional; used by local LLM stack)[/dim]"
        )
