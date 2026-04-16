"""LLM stack management commands: up, down, pull, setup, status, logs, shell."""

import socket
import time
from http.client import HTTPException, HTTPSConnection
from pathlib import Path

import click
from rich.console import Console

from ai_shell.cli import CONTEXT_SETTINGS
from ai_shell.config import load_config
from ai_shell.container import ContainerManager
from ai_shell.defaults import (
    LOBECHAT_CONTAINER,
    OLLAMA_CONTAINER,
    OLLAMA_DATA_VOLUME,
    WEBUI_CONTAINER,
    WEBUI_DATA_VOLUME,
)
from ai_shell.gpu import get_vram_info, get_vram_processes

console = Console(stderr=True)

_LOW_MEMORY_THRESHOLD_GIB = 30  # 27B+ models need ~30 GiB
_OLLAMA_REGISTRY_HOST = "registry.ollama.ai"
_MANIFEST_PROBE_TIMEOUT = 5.0


def _parse_model_ref(ref: str) -> tuple[str, str, str]:
    """Parse an Ollama model reference into (namespace, name, tag).

    - "foo"          -> ("library", "foo", "latest")
    - "foo:tag"      -> ("library", "foo", "tag")
    - "ns/foo"       -> ("ns", "foo", "latest")
    - "ns/foo:tag"   -> ("ns", "foo", "tag")
    """
    tag = "latest"
    if ":" in ref:
        ref, tag = ref.rsplit(":", 1)
    if "/" in ref:
        namespace, name = ref.split("/", 1)
    else:
        namespace, name = "library", ref
    return namespace, name, tag


def _manifest_exists(model_ref: str) -> bool | None:
    """Probe the Ollama registry for a model manifest.

    Returns True if the manifest exists (HTTP 200), False if it
    definitively does not (HTTP 404), or None if the check could not
    be completed (network error, unexpected status). Callers should
    treat None as "don't block" so an unreachable registry never
    prevents a pull that might succeed from a local mirror.
    """
    namespace, name, tag = _parse_model_ref(model_ref)
    path = f"/v2/{namespace}/{name}/manifests/{tag}"
    connection = HTTPSConnection(_OLLAMA_REGISTRY_HOST, timeout=_MANIFEST_PROBE_TIMEOUT)
    try:
        connection.request(
            "HEAD",
            path,
            headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"},
        )
        response = connection.getresponse()
        response.read()  # drain so the connection is reusable / cleanly closed
        if response.status == 200:
            return True
        if response.status == 404:
            return False
        return None
    except (OSError, HTTPException):
        return None
    finally:
        connection.close()


def _tag_list_url(model_ref: str) -> str:
    """Return the ollama.com tag list URL for a model reference."""
    namespace, name, _ = _parse_model_ref(model_ref)
    if namespace == "library":
        return f"https://ollama.com/library/{name}/tags"
    return f"https://ollama.com/{namespace}/{name}/tags"


def _validate_models_or_abort(*model_refs: str) -> None:
    """Fail fast if any referenced model tag is missing from the registry.

    Definite 404s abort with a message pointing at the tag list page.
    Network / unexpected errors are ignored so the check never blocks
    a pull when the registry is simply unreachable (offline use, local
    mirror, transient DNS issue, etc.).
    """
    missing: list[str] = []
    for ref in model_refs:
        if _manifest_exists(ref) is False:
            missing.append(ref)
    if not missing:
        return
    console.print(
        "[bold red]Error:[/bold red] the following model tag(s) were not found "
        "on the Ollama registry:"
    )
    for ref in missing:
        console.print(f"  - [cyan]{ref}[/cyan]  (tags: {_tag_list_url(ref)})")
    console.print(
        "\nUpdate [bold]primary_model[/bold] / [bold]fallback_model[/bold] in "
        "your ai-shell config to a valid tag and retry."
    )
    raise click.Abort()


def _lan_ip() -> str | None:
    """Return the host's primary LAN IPv4 address, or None if undetectable.

    Uses a UDP socket's routing-table selection without actually sending
    traffic. Works on Linux, Mac, and WSL2. On WSL2 this returns the
    WSL VM's eth0 address (typically 172.x.x.x), which is reachable from
    the Windows host but not the broader LAN unless WSL mirrored mode or
    a Windows portproxy is configured.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = str(s.getsockname()[0])
    except OSError:
        return None
    if ip.startswith("127."):
        return None
    return ip


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


@click.group("llm", context_settings=CONTEXT_SETTINGS)
@click.pass_context
def llm_group(ctx):
    """Manage the local LLM stack (Ollama + Open WebUI + LobeChat)."""


@llm_group.command("up")
@click.pass_context
def llm_up(ctx):
    """Start the LLM stack (Ollama + Open WebUI + LobeChat)."""
    manager = _get_manager(ctx)
    console.print("[bold]Starting LLM stack...[/bold]")
    _warn_if_low_memory()

    manager.ensure_ollama()
    console.print(f"  Ollama API:  http://localhost:{manager.config.ollama_port}")

    manager.ensure_webui()
    console.print(f"  Open WebUI:  http://localhost:{manager.config.webui_port}")

    manager.ensure_lobechat()
    console.print(
        f"  LobeChat:    http://localhost:{manager.config.lobechat_port}  [dim](recommended)[/dim]"
    )

    lan = _lan_ip()
    if lan:
        console.print("\n[bold]LAN access[/bold] (bound to 0.0.0.0):")
        console.print(f"  Ollama API:  http://{lan}:{manager.config.ollama_port}")
        console.print(f"  Open WebUI:  http://{lan}:{manager.config.webui_port}")
        console.print(f"  LobeChat:    http://{lan}:{manager.config.lobechat_port}")

    console.print("\n[bold green]LLM stack is running.[/bold green]")
    console.print("If this is your first time, run: [bold]ai-shell llm setup[/bold]")


@llm_group.command("down")
@click.pass_context
def llm_down(ctx):
    """Stop the LLM stack."""
    manager = _get_manager(ctx)
    console.print("[bold]Stopping LLM stack...[/bold]")

    for name in [LOBECHAT_CONTAINER, WEBUI_CONTAINER, OLLAMA_CONTAINER]:
        status = manager.container_status(name)
        if status == "running":
            manager.stop_container(name)
            console.print(f"  Stopped: {name}")
        elif status is not None:
            console.print(f"  Already stopped: {name}")
        else:
            console.print(f"  Not found: {name}")

    console.print("[bold green]LLM stack stopped.[/bold green]")


@llm_group.command("clean")
@click.option(
    "--volumes",
    "-v",
    "remove_volumes",
    is_flag=True,
    help="Also remove named volumes (deletes downloaded models + WebUI chat history).",
)
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help="Skip the confirmation prompt.",
)
@click.pass_context
def llm_clean(ctx, remove_volumes: bool, assume_yes: bool):
    """Stop and remove all LLM containers (LobeChat, Open WebUI, Ollama).

    By default, named volumes are preserved so downloaded models survive.
    Pass --volumes to also wipe volumes (requires re-pulling models).
    """
    manager = _get_manager(ctx)

    if not assume_yes:
        scope = "containers + volumes (downloaded models will be deleted)"
        if not remove_volumes:
            scope = "containers only (volumes preserved)"
        console.print(f"[bold]About to remove:[/bold] {scope}")
        if not click.confirm("Continue?", default=False):
            console.print("Aborted.")
            return

    console.print("[bold]Cleaning LLM stack...[/bold]")

    for name in [LOBECHAT_CONTAINER, WEBUI_CONTAINER, OLLAMA_CONTAINER]:
        if manager.container_status(name) is None:
            console.print(f"  Not found: {name}")
            continue
        manager.remove_container(name)
        console.print(f"  Removed: {name}")

    if remove_volumes:
        for volume in [OLLAMA_DATA_VOLUME, WEBUI_DATA_VOLUME]:
            if manager.remove_volume(volume):
                console.print(f"  Removed volume: {volume}")
            else:
                console.print(f"  Volume not found: {volume}")

    console.print("[bold green]LLM stack cleaned.[/bold green]")
    console.print("Run [bold]ai-shell llm up[/bold] to recreate containers.")


@llm_group.command("pull")
@click.pass_context
def llm_pull(ctx):
    """Pull LLM models into Ollama."""
    manager = _get_manager(ctx)
    config = manager.config

    _validate_models_or_abort(config.primary_model, config.fallback_model)

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

    # Fail fast on invalid model tags before touching Docker / pulling anything.
    _validate_models_or_abort(config.primary_model, config.fallback_model)

    # Start the stack
    console.print("[bold]Starting LLM stack...[/bold]")
    _warn_if_low_memory()
    manager.ensure_ollama()
    manager.ensure_webui()
    manager.ensure_lobechat()

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

    console.print("\n[bold green]============================================[/bold green]")
    console.print("[bold green] Setup complete![/bold green]")
    console.print(f"\n  LobeChat:    http://localhost:{config.lobechat_port}  (recommended)")
    console.print(f"  Open WebUI:  http://localhost:{config.webui_port}")
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
    lobechat_running = manager.container_status(LOBECHAT_CONTAINER) == "running"

    console.print("[bold]Container status:[/bold]")
    for name, running in [
        (OLLAMA_CONTAINER, ollama_running),
        (WEBUI_CONTAINER, webui_running),
        (LOBECHAT_CONTAINER, lobechat_running),
    ]:
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
    lobechat_url = f"http://localhost:{config.lobechat_port}"
    if lobechat_running:
        console.print(
            f"  LobeChat:           [cyan]{lobechat_url}[/cyan]  [bold](recommended)[/bold]"
        )
    else:
        console.print(f"  LobeChat:           [dim]{lobechat_url}[/dim] (not running)")
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

    lan = _lan_ip()
    if lan:
        console.print("\n[bold]LAN access[/bold] (bound to 0.0.0.0):")
        console.print(f"  Ollama API:         [cyan]http://{lan}:{config.ollama_port}[/cyan]")
        console.print(f"  Open WebUI:         [cyan]http://{lan}:{config.webui_port}[/cyan]")
        console.print(f"  LobeChat:           [cyan]http://{lan}:{config.lobechat_port}[/cyan]")

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
        for name in [OLLAMA_CONTAINER, WEBUI_CONTAINER, LOBECHAT_CONTAINER]:
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
