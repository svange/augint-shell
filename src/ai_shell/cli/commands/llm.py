"""LLM stack management commands: up, down, pull, setup, status, logs, shell."""

import time
from pathlib import Path

import click
from rich.console import Console

from ai_shell.config import load_config
from ai_shell.container import ContainerManager
from ai_shell.defaults import OLLAMA_CONTAINER, WEBUI_CONTAINER

console = Console(stderr=True)


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
    """Show status of LLM stack and loaded models."""
    manager = _get_manager(ctx)

    console.print("[bold]Container status:[/bold]")
    for name in [OLLAMA_CONTAINER, WEBUI_CONTAINER]:
        status = manager.container_status(name)
        if status == "running":
            console.print(f"  {name}: [green]{status}[/green]")
        elif status is not None:
            console.print(f"  {name}: [yellow]{status}[/yellow]")
        else:
            console.print(f"  {name}: [red]not found[/red]")

    # Show models if ollama is running
    if manager.container_status(OLLAMA_CONTAINER) == "running":
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
        # Use docker CLI for multi-container following
        import os
        import sys

        sys.stdout.flush()
        sys.stderr.flush()
        os.execvp(
            "docker",
            ["docker", "logs", "-f", OLLAMA_CONTAINER],
        )
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
