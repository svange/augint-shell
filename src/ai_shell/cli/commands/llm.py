"""LLM stack management commands: up, down, pull, setup, status, logs, shell.

Stack flags (applied to up/down/clean/setup):
    --webui     Open WebUI (OpenAI-style chat UI backed by Ollama). Kokoro
                TTS starts with it by default (wired as WebUI's "read aloud"
                backend); use --no-voice to skip.
    --voice     Kokoro-FastAPI (local OpenAI-compatible TTS) standalone.
    --no-voice  Opt-out: skip Kokoro even when --webui is set.
    --n8n       n8n workflow automation engine (standalone).
    --all       Enable every optional stack.

``llm up`` with no flags starts only the base Ollama container.
"""

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
    KOKORO_CONTAINER,
    N8N_CONTAINER,
    N8N_DATA_VOLUME,
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


def _resolve_stacks(
    webui: bool, voice: bool, no_voice: bool, n8n: bool, all_: bool
) -> tuple[bool, bool, bool]:
    """Resolve stack flags into concrete (webui, voice, n8n) enablement.

    Rules:
    - ``--all`` turns on every optional stack.
    - ``--webui`` implies ``--voice`` (Kokoro is wired as WebUI's TTS backend).
    - ``--no-voice`` is the opt-out and always wins.
    - ``--n8n`` is standalone with no implied sibling stacks.

    Extension pattern: when we add ``--libre`` / ``--dify`` / ``--hands``,
    they become additional parameters here with the same ``all_`` expansion.
    """
    if all_:
        webui = True
        voice = True
        n8n = True
    if webui:
        voice = True
    if no_voice:
        voice = False
    return webui, voice, n8n


# Shared decorators for stack flags on up/down/clean/setup.
def _stack_flags(func):
    func = click.option("--all", "all_", is_flag=True, help="Enable every optional stack.")(func)
    func = click.option("--n8n", is_flag=True, help="n8n workflow automation engine (port 5678).")(
        func
    )
    func = click.option(
        "--no-voice",
        "no_voice",
        is_flag=True,
        help="Skip Kokoro TTS even when --webui is set.",
    )(func)
    func = click.option(
        "--voice",
        is_flag=True,
        help="Kokoro local TTS (OpenAI-compatible, port 8880). Implied by --webui.",
    )(func)
    func = click.option(
        "--webui", is_flag=True, help="Open WebUI (Kokoro TTS wired automatically)."
    )(func)
    return func


@click.group("llm", context_settings=CONTEXT_SETTINGS)
@click.pass_context
def llm_group(ctx):
    """Manage the local LLM stack (Ollama + optional Open WebUI / TTS)."""


@llm_group.command("up")
@_stack_flags
@click.pass_context
def llm_up(ctx, webui: bool, voice: bool, no_voice: bool, n8n: bool, all_: bool):
    """Start the LLM stack.

    With no flags, starts only Ollama. ``--webui`` brings up Open WebUI and
    (by default) wires Kokoro TTS as its "read aloud" backend; pass
    ``--no-voice`` to skip TTS. ``--voice`` alone runs Kokoro standalone.
    ``--n8n`` brings up n8n workflow automation.
    """
    webui, voice, n8n = _resolve_stacks(webui, voice, no_voice, n8n, all_)
    manager = _get_manager(ctx)
    config = manager.config
    console.print("[bold]Starting LLM stack...[/bold]")
    _warn_if_low_memory()

    manager.ensure_ollama()
    console.print(f"  Ollama API:  http://localhost:{config.ollama_port}")

    if voice:
        manager.ensure_kokoro()
        console.print(f"  Kokoro TTS:  http://localhost:{config.kokoro_port}/v1")

    if webui:
        manager.ensure_webui(voice_enabled=voice)
        console.print(f"  Open WebUI:  http://localhost:{config.webui_port}")

    if n8n:
        manager.ensure_n8n()
        console.print(f"  n8n:         http://localhost:{config.n8n_port}")

    lan = _lan_ip()
    if lan:
        console.print("\n[bold]LAN access[/bold] (bound to 0.0.0.0):")
        console.print(f"  Ollama API:  http://{lan}:{config.ollama_port}")
        if voice:
            console.print(f"  Kokoro TTS:  http://{lan}:{config.kokoro_port}/v1")
        if webui:
            console.print(f"  Open WebUI:  http://{lan}:{config.webui_port}")
        if n8n:
            console.print(f"  n8n:         http://{lan}:{config.n8n_port}")

    console.print("\n[bold green]LLM stack is running.[/bold green]")


@llm_group.command("down")
@_stack_flags
@click.pass_context
def llm_down(ctx, webui: bool, voice: bool, no_voice: bool, n8n: bool, all_: bool):
    """Stop containers in the LLM stack.

    With no flags, stops only Ollama. Use stack flags or --all to stop
    additional stacks.
    """
    webui, voice, n8n = _resolve_stacks(webui, voice, no_voice, n8n, all_)
    manager = _get_manager(ctx)
    console.print("[bold]Stopping LLM stack...[/bold]")

    targets = [OLLAMA_CONTAINER]
    if webui:
        targets.append(WEBUI_CONTAINER)
    if voice:
        targets.append(KOKORO_CONTAINER)
    if n8n:
        targets.append(N8N_CONTAINER)

    for name in targets:
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
@_stack_flags
@click.option(
    "--wipe",
    is_flag=True,
    help="Also wipe persistent data (models, chat history). Irreversible.",
)
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@click.pass_context
def llm_clean(
    ctx,
    webui: bool,
    voice: bool,
    no_voice: bool,
    n8n: bool,
    all_: bool,
    wipe: bool,
    assume_yes: bool,
):
    """Remove LLM containers and (with --wipe) persistent data.

    With no stack flags, removes the base Ollama container only. Use stack
    flags or --all to also remove other stacks. --wipe additionally deletes
    named Docker volumes.
    """
    webui, voice, n8n = _resolve_stacks(webui, voice, no_voice, n8n, all_)
    manager = _get_manager(ctx)

    targets = [OLLAMA_CONTAINER]
    if webui:
        targets.append(WEBUI_CONTAINER)
    if voice:
        targets.append(KOKORO_CONTAINER)
    if n8n:
        targets.append(N8N_CONTAINER)

    volumes: list[str] = []
    if wipe:
        volumes.append(OLLAMA_DATA_VOLUME)
        if webui:
            volumes.append(WEBUI_DATA_VOLUME)
        if n8n:
            volumes.append(N8N_DATA_VOLUME)

    if not assume_yes:
        if wipe:
            scope = "containers + volumes (models and chat history will be deleted)"
        else:
            scope = "containers only (data preserved)"
        console.print(f"[bold]About to remove:[/bold] {scope}")
        if not click.confirm("Continue?", default=False):
            console.print("Aborted.")
            return

    console.print("[bold]Cleaning LLM stack...[/bold]")
    for name in targets:
        if manager.container_status(name) is None:
            console.print(f"  Not found: {name}")
            continue
        manager.remove_container(name)
        console.print(f"  Removed: {name}")

    if wipe:
        for volume in volumes:
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
@_stack_flags
@click.pass_context
def llm_setup(ctx, webui: bool, voice: bool, no_voice: bool, n8n: bool, all_: bool):
    """First-time setup: start stack, pull models, configure context.

    Accepts the same stack flags as ``llm up``. With no flags, sets up only
    the base Ollama container and pulls the configured primary/fallback models.
    """
    webui, voice, n8n = _resolve_stacks(webui, voice, no_voice, n8n, all_)
    manager = _get_manager(ctx)
    config = manager.config

    _validate_models_or_abort(config.primary_model, config.fallback_model)

    console.print("[bold]Starting LLM stack...[/bold]")
    _warn_if_low_memory()
    manager.ensure_ollama()
    if voice:
        manager.ensure_kokoro()
    if webui:
        manager.ensure_webui(voice_enabled=voice)
    if n8n:
        manager.ensure_n8n()

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

    console.print(f"\n[bold]Pulling primary model: {config.primary_model}...[/bold]")
    output = manager.exec_in_ollama(["ollama", "pull", config.primary_model])
    console.print(output)

    console.print(f"\n[bold]Pulling fallback model: {config.fallback_model}...[/bold]")
    output = manager.exec_in_ollama(["ollama", "pull", config.fallback_model])
    console.print(output)

    console.print("\n[bold green]============================================[/bold green]")
    console.print("[bold green] Setup complete![/bold green]")
    console.print(f"  Ollama API:  http://localhost:{config.ollama_port}")
    if voice:
        console.print(f"  Kokoro TTS:  http://localhost:{config.kokoro_port}/v1")
    if webui:
        console.print(f"  Open WebUI:  http://localhost:{config.webui_port}")
    if n8n:
        console.print(f"  n8n:         http://localhost:{config.n8n_port}")
    console.print(f"\n  Primary model:  {config.primary_model}")
    console.print(f"  Fallback model: {config.fallback_model}")
    console.print(f"  Context window: {config.context_size} tokens")
    console.print("[bold green]============================================[/bold green]")


def _render_container_row(manager: ContainerManager, name: str, label: str) -> None:
    """Print one row of the `llm status` grid, colored by runtime state."""
    status = manager.container_status(name)
    if status == "running":
        console.print(f"  [green]{label:<20}[/green] [green]running[/green]  [dim]({name})[/dim]")
    elif status is not None:
        console.print(
            f"  [yellow]{label:<20}[/yellow] [yellow]{status}[/yellow]  [dim]({name})[/dim]"
        )
    else:
        console.print(f"  [dim]{label:<20} absent   ({name})[/dim]")


@llm_group.command("status")
@click.pass_context
def llm_status(ctx):
    """Show status of all known LLM containers, URLs, and loaded models."""
    manager = _get_manager(ctx)
    config = manager.config

    console.print("[bold]Base stack[/bold]")
    _render_container_row(manager, OLLAMA_CONTAINER, "Ollama")

    console.print("\n[bold]WebUI stack[/bold]")
    _render_container_row(manager, WEBUI_CONTAINER, "Open WebUI")

    console.print("\n[bold]Voice stack[/bold]")
    _render_container_row(manager, KOKORO_CONTAINER, "Kokoro TTS")

    console.print("\n[bold]n8n stack[/bold]")
    _render_container_row(manager, N8N_CONTAINER, "n8n")

    console.print("\n[bold]Access URLs:[/bold]")

    def _url(label: str, name: str, url: str) -> None:
        running = manager.container_status(name) == "running"
        color = "cyan" if running else "dim"
        suffix = "" if running else "  (not running)"
        console.print(f"  {label:<18}  [{color}]{url}[/{color}]{suffix}")

    _url("Ollama API:", OLLAMA_CONTAINER, f"http://localhost:{config.ollama_port}")
    _url("  OpenAI-compat:", OLLAMA_CONTAINER, f"http://localhost:{config.ollama_port}/v1")
    _url("Open WebUI:", WEBUI_CONTAINER, f"http://localhost:{config.webui_port}")
    _url("Kokoro TTS:", KOKORO_CONTAINER, f"http://localhost:{config.kokoro_port}/v1")
    _url("n8n:", N8N_CONTAINER, f"http://localhost:{config.n8n_port}")

    lan = _lan_ip()
    if lan:
        console.print("\n[bold]LAN access[/bold] (bound to 0.0.0.0):")
        console.print(f"  Ollama API:         http://{lan}:{config.ollama_port}")
        console.print(f"  Open WebUI:         http://{lan}:{config.webui_port}")
        console.print(f"  Kokoro TTS:         http://{lan}:{config.kokoro_port}/v1")
        console.print(f"  n8n:                http://{lan}:{config.n8n_port}")

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
        manager.container_logs(OLLAMA_CONTAINER, follow=True)
    else:
        for name in [
            OLLAMA_CONTAINER,
            WEBUI_CONTAINER,
            KOKORO_CONTAINER,
            N8N_CONTAINER,
        ]:
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
