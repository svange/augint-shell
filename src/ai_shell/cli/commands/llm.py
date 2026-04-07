"""LLM stack management commands: up, down, pull, setup, status, logs, shell."""

import time
from pathlib import Path

import click
from rich.console import Console

from ai_shell.config import load_config
from ai_shell.container import ContainerManager
from ai_shell.defaults import OLLAMA_CONTAINER, WEBUI_CONTAINER
from ai_shell.gpu import get_vram_info, get_vram_processes

console = Console(stderr=True)

_LOW_MEMORY_THRESHOLD_GIB = 30  # 27B+ models need ~30 GiB


def _warn_if_low_memory() -> None:
    """Check system memory and warn if it may be insufficient for large models."""
    try:
        meminfo = Path("/proc/meminfo").read_text()
    except OSError:
        return  # Not on Linux, skip silently

    mem_total_gib = 0.0
    swap_total_gib = 0.0
    for line in meminfo.splitlines():
        if line.startswith("MemTotal:"):
            mem_total_gib = int(line.split()[1]) / (1024 * 1024)
        elif line.startswith("SwapTotal:"):
            swap_total_gib = int(line.split()[1]) / (1024 * 1024)

    total_gib = mem_total_gib + swap_total_gib
    if total_gib < _LOW_MEMORY_THRESHOLD_GIB:
        console.print(
            f"\n[yellow bold]Warning:[/yellow bold] System has "
            f"{mem_total_gib:.1f} GiB RAM + {swap_total_gib:.1f} GiB swap "
            f"= {total_gib:.1f} GiB total."
        )
        console.print(
            "[yellow]Large models (27B+) need ~30 GiB. "
            "To increase, edit [bold]%UserProfile%\\.wslconfig[/bold] on Windows:[/yellow]"
        )
        console.print("[yellow]  [wsl2][/yellow]")
        console.print("[yellow]  memory=32GB[/yellow]")
        console.print("[yellow]  swap=32GB[/yellow]")
        console.print("[yellow]Then run: [bold]wsl --shutdown[/bold]\n[/yellow]")


def _get_manager(ctx) -> ContainerManager:
    """Create ContainerManager from Click context."""
    project = ctx.obj.get("project") if ctx.obj else None
    config = load_config(project_override=project, project_dir=Path.cwd())
    return ContainerManager(config)


@click.group("llm")
@click.pass_context
def llm_group(ctx):
    """Manage the local LLM stack (Ollama + Open WebUI)."""


@llm_group.command("up")
@click.pass_context
def llm_up(ctx):
    """Start the LLM stack (Ollama + Open WebUI)."""
    manager = _get_manager(ctx)
    console.print("[bold]Starting LLM stack...[/bold]")
    _warn_if_low_memory()

    manager.ensure_ollama()
    console.print(f"  Ollama API:  http://localhost:{manager.config.ollama_port}")

    manager.ensure_webui()
    console.print(f"  Open WebUI:  http://localhost:{manager.config.webui_port}")

    console.print("\n[bold green]LLM stack is running.[/bold green]")
    console.print("If this is your first time, run: [bold]ai-shell llm setup[/bold]")


@llm_group.command("down")
@click.pass_context
def llm_down(ctx):
    """Stop the LLM stack."""
    manager = _get_manager(ctx)
    console.print("[bold]Stopping LLM stack...[/bold]")

    for name in [WEBUI_CONTAINER, OLLAMA_CONTAINER]:
        status = manager.container_status(name)
        if status == "running":
            manager.stop_container(name)
            console.print(f"  Stopped: {name}")
        elif status is not None:
            console.print(f"  Already stopped: {name}")
        else:
            console.print(f"  Not found: {name}")

    console.print("[bold green]LLM stack stopped.[/bold green]")


@llm_group.command("pull")
@click.pass_context
def llm_pull(ctx):
    """Pull LLM models into Ollama."""
    manager = _get_manager(ctx)
    config = manager.config

    console.print(f"[bold]Pulling primary model: {config.primary_model}...[/bold]")
    output = manager.exec_in_ollama(["ollama", "pull", config.primary_model])
    console.print(output)

    console.print(f"\n[bold]Pulling fallback model: {config.fallback_model}...[/bold]")
    output = manager.exec_in_ollama(["ollama", "pull", config.fallback_model])
    console.print(output)

    console.print("\n[bold]Available models:[/bold]")
    output = manager.exec_in_ollama(["ollama", "list"])
    console.print(output)


@llm_group.command("setup")
@click.pass_context
def llm_setup(ctx):
    """First-time setup: start stack, pull models, configure context window."""
    manager = _get_manager(ctx)
    config = manager.config

    # Start the stack
    console.print("[bold]Starting LLM stack...[/bold]")
    _warn_if_low_memory()
    manager.ensure_ollama()
    manager.ensure_webui()

    # Wait for Ollama to be ready
    console.print("[bold]Waiting for Ollama to be ready...[/bold]")
    for i in range(10):
        try:
            output = manager.exec_in_ollama(["ollama", "list"])
            if output is not None:
                break
        except Exception:
            pass
        console.print(f"  Waiting... ({i + 1}/10)")
        time.sleep(2)
    else:
        console.print("[bold red]Ollama failed to start after 20s[/bold red]")
        raise click.Abort()

    # Pull models
    console.print(f"\n[bold]Pulling primary model: {config.primary_model}...[/bold]")
    output = manager.exec_in_ollama(["ollama", "pull", config.primary_model])
    console.print(output)

    console.print(f"\n[bold]Pulling fallback model: {config.fallback_model}...[/bold]")
    output = manager.exec_in_ollama(["ollama", "pull", config.fallback_model])
    console.print(output)

    # Configure context window
    console.print(f"\n[bold]Configuring context window ({config.context_size} tokens)...[/bold]")
    for model in [config.primary_model, config.fallback_model]:
        modelfile = f"FROM {model}\nPARAMETER num_ctx {config.context_size}\n"
        # Write modelfile and create model
        manager.exec_in_ollama(
            [
                "sh",
                "-c",
                f'printf "{modelfile}" > /tmp/Modelfile && '
                f"ollama create {model} -f /tmp/Modelfile && rm -f /tmp/Modelfile",
            ]
        )

    console.print("\n[bold green]============================================[/bold green]")
    console.print("[bold green] Setup complete![/bold green]")
    console.print(f"\n  Open WebUI:  http://localhost:{config.webui_port}")
    console.print(f"  Ollama API:  http://localhost:{config.ollama_port}")
    console.print(f"\n  Primary model:  {config.primary_model}")
    console.print(f"  Fallback model: {config.fallback_model}")
    console.print(f"  Context window: {config.context_size} tokens")
    console.print("[bold green]============================================[/bold green]")


@llm_group.command("status")
@click.pass_context
def llm_status(ctx):
    """Show status of LLM stack, URLs, and loaded models."""
    manager = _get_manager(ctx)
    config = manager.config
    ollama_running = manager.container_status(OLLAMA_CONTAINER) == "running"
    webui_running = manager.container_status(WEBUI_CONTAINER) == "running"

    console.print("[bold]Container status:[/bold]")
    for name, running in [(OLLAMA_CONTAINER, ollama_running), (WEBUI_CONTAINER, webui_running)]:
        status = manager.container_status(name)
        if running:
            console.print(f"  {name}: [green]{status}[/green]")
        elif status is not None:
            console.print(f"  {name}: [yellow]{status}[/yellow]")
        else:
            console.print(f"  {name}: [red]not found[/red]")

    console.print("\n[bold]Access URLs:[/bold]")
    ollama_url = f"http://localhost:{config.ollama_port}"
    webui_url = f"http://localhost:{config.webui_port}"
    if ollama_running:
        console.print(f"  Ollama API:         [cyan]{ollama_url}[/cyan]")
        console.print(f"  OpenAI-compatible:  [cyan]{ollama_url}/v1[/cyan]")
    else:
        console.print(f"  Ollama API:         [dim]{ollama_url}[/dim] (not running)")
        console.print(f"  OpenAI-compatible:  [dim]{ollama_url}/v1[/dim] (not running)")
    if webui_running:
        console.print(f"  Open WebUI:         [cyan]{webui_url}[/cyan]")
    else:
        console.print(f"  Open WebUI:         [dim]{webui_url}[/dim] (not running)")

    console.print("\n[bold]Configuration:[/bold]")
    console.print(f"  Primary model:   {config.primary_model}")
    console.print(f"  Fallback model:  {config.fallback_model}")
    console.print(f"  Context window:  {config.context_size} tokens")

    vram = get_vram_info()
    if vram is not None:
        console.print("\n[bold]GPU VRAM:[/bold]")
        console.print(
            f"  Total: {vram['total'] / 1024**3:.1f} GiB  "
            f"Used: {vram['used'] / 1024**3:.1f} GiB  "
            f"Free: {vram['free'] / 1024**3:.1f} GiB"
        )
        processes = get_vram_processes()
        console.print("\n  [bold]VRAM consumers:[/bold]")
        if processes:
            for pid, vram_mb, name in sorted(processes, key=lambda x: x[1], reverse=True):
                console.print(f"    PID {pid:<8} {name:<20} {vram_mb / 1024:.1f} GiB")
        else:
            console.print("  (none)")

    if ollama_running:
        console.print("\n[bold]Available models:[/bold]")
        output = manager.exec_in_ollama(["ollama", "list"])
        console.print(output)


@llm_group.command("logs")
@click.option("--follow", "-f", is_flag=True, help="Follow log output.")
@click.pass_context
def llm_logs(ctx, follow):
    """Tail logs from the LLM stack."""
    manager = _get_manager(ctx)
    if follow:
        manager.container_logs(OLLAMA_CONTAINER, follow=True)
    else:
        for name in [OLLAMA_CONTAINER, WEBUI_CONTAINER]:
            status = manager.container_status(name)
            if status is not None:
                console.print(f"\n[bold]--- {name} ---[/bold]")
                manager.container_logs(name, follow=False, tail=50)


@llm_group.command("shell")
@click.pass_context
def llm_shell(ctx):
    """Open a bash shell in the Ollama container."""
    manager = _get_manager(ctx)
    status = manager.container_status(OLLAMA_CONTAINER)
    if status != "running":
        console.print("[red]Ollama is not running. Run: ai-shell llm up[/red]")
        raise click.Abort()
    console.print("[bold]Opening shell in Ollama container...[/bold]")
    manager.exec_interactive(OLLAMA_CONTAINER, ["/bin/bash"])
