"""LLM stack management commands: up, down, pull, setup, status, logs, shell.

Stack flags (applied to up/down/clean/setup):
    --webui        Open WebUI (OpenAI-style chat UI backed by Ollama). Kokoro
                   TTS starts with it by default (wired as WebUI's "read aloud"
                   backend); use --no-voice to skip.
    --voice        Kokoro-FastAPI (local OpenAI-compatible TTS) standalone.
    --no-voice     Opt-out: skip Kokoro even when --webui is set.
    --whisper      Speaches (local OpenAI-compatible STT) standalone.
    --voice-agent  Experimental Pipecat-based voice agent (built locally).
    --n8n          n8n workflow automation engine (standalone).
    --all          Enable every optional stack.

``llm up`` with no flags starts only the base Ollama container.
"""

import re
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
    COMFYUI_CONTAINER,
    COMFYUI_DATA_VOLUME,
    KOKORO_CONTAINER,
    N8N_CONTAINER,
    N8N_DATA_VOLUME,
    OLLAMA_CONTAINER,
    OLLAMA_DATA_VOLUME,
    VOICE_AGENT_CONTAINER,
    VOICE_AGENT_DATA_VOLUME,
    WEBUI_CONTAINER,
    WEBUI_DATA_VOLUME,
    WHISPER_CONTAINER,
    WHISPER_DATA_VOLUME,
)
from ai_shell.gpu import get_vram_info, get_vram_processes

console = Console(stderr=True)

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
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
    connection = HTTPSConnection(_OLLAMA_REGISTRY_HOST, timeout=_MANIFEST_PROBE_TIMEOUT)  # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected
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
        "\nUpdate the relevant [bold]*_chat_model[/bold] / [bold]*_coding_model[/bold] "
        "entry (or [bold]extra_models[/bold]) in your ai-shell config to a valid tag and retry."
    )
    raise click.Abort()


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences and collapse carriage-return overwrites.

    ``ollama pull`` emits VT100 codes (bold, erase-line) and ``\\r``-based
    progress bars that render as garbage in non-VT100 terminals (e.g.
    PowerShell). This function strips all of that and returns only the
    final state of each progress line.
    """
    text = _ANSI_ESCAPE_RE.sub("", text)
    # Progress bars use \r to overwrite the line; keep only the last segment.
    lines: list[str] = []
    for line in text.split("\n"):
        segments = line.split("\r")
        final = segments[-1].strip()
        if final:
            lines.append(final)
    return "\n".join(lines)


def _pull_models(manager: ContainerManager, models: tuple[str, ...] | list[str]) -> None:
    """Pull one or more Ollama models with a spinner and clean output."""
    for model in models:
        with console.status(f"[bold]Pulling {model}...[/bold]", spinner="dots"):
            output = manager.exec_in_ollama(["ollama", "pull", model])
        clean = _strip_ansi(output)
        if "success" in clean.lower():
            console.print(f"  [green]Pulled {model}[/green]")
        else:
            console.print(f"  [yellow]{model}:[/yellow]")
            console.print(clean)


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
    webui: bool,
    voice: bool,
    no_voice: bool,
    whisper: bool,
    voice_agent: bool,
    n8n: bool,
    image_gen: bool,
    all_: bool,
) -> tuple[bool, bool, bool, bool, bool, bool]:
    """Resolve stack flags into ``(webui, voice, whisper, voice_agent, n8n, image_gen)``.

    Rules:
    - ``--all`` turns on every optional stack.
    - ``--webui`` implies ``--voice`` (Kokoro is wired as WebUI's TTS backend).
    - ``--no-voice`` is the opt-out and always wins.
    - ``--whisper`` is standalone with no implied sibling stacks.
    - ``--voice-agent`` is standalone; it does NOT auto-start Whisper/Kokoro/Ollama
      because those are independent singletons (start them yourself if needed).
    - ``--n8n`` is standalone with no implied sibling stacks.
    - ``--image-gen`` is standalone (runs ComfyUI); when combined with
      ``--webui`` WebUI is pre-wired to use it.

    Extension pattern: when we add ``--libre`` / ``--dify`` / ``--hands``,
    they become additional parameters here with the same ``all_`` expansion.
    """
    if all_:
        webui = True
        voice = True
        whisper = True
        voice_agent = True
        n8n = True
        image_gen = True
    if webui:
        voice = True
    if no_voice:
        voice = False
    return webui, voice, whisper, voice_agent, n8n, image_gen


# Shared decorators for stack flags on up/down/clean/setup.
def _stack_flags(func):
    func = click.option("--all", "all_", is_flag=True, help="Enable every optional stack.")(func)
    func = click.option(
        "--env",
        "env_file",
        type=click.Path(exists=True, dir_okay=False),
        default=None,
        help="Env file with API keys (e.g. .env.augint-shell). Keys are passed to n8n and WebUI.",
    )(func)
    func = click.option(
        "--image-gen",
        "image_gen",
        is_flag=True,
        help="ComfyUI image generation (port 8188). Wires into WebUI when --webui is set.",
    )(func)
    func = click.option("--n8n", is_flag=True, help="n8n workflow automation engine (port 5678).")(
        func
    )
    func = click.option(
        "--voice-agent",
        "voice_agent",
        is_flag=True,
        help="Experimental Pipecat voice agent (built locally, port 8010).",
    )(func)
    func = click.option(
        "--whisper",
        is_flag=True,
        help="Speaches local STT (OpenAI-compatible, port 8001).",
    )(func)
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
def llm_up(
    ctx,
    webui: bool,
    voice: bool,
    no_voice: bool,
    whisper: bool,
    voice_agent: bool,
    n8n: bool,
    image_gen: bool,
    all_: bool,
    env_file: str | None,
):
    """Start the LLM stack.

    With no flags, starts only Ollama. ``--webui`` brings up Open WebUI and
    (by default) wires Kokoro TTS as its "read aloud" backend; pass
    ``--no-voice`` to skip TTS. ``--voice`` alone runs Kokoro standalone.
    ``--whisper`` brings up Speaches STT. ``--voice-agent`` brings up the
    experimental Pipecat voice agent. ``--n8n`` brings up n8n workflow
    automation. ``--image-gen`` brings up ComfyUI (wired into WebUI when
    ``--webui`` is also set). ``--env <file>`` passes API keys to n8n and
    WebUI, and ``HF_TOKEN`` to ComfyUI for FLUX.1-dev downloads.
    """
    webui, voice, whisper, voice_agent, n8n, image_gen = _resolve_stacks(
        webui, voice, no_voice, whisper, voice_agent, n8n, image_gen, all_
    )
    env_path = Path(env_file) if env_file else None
    manager = _get_manager(ctx)
    config = manager.config
    console.print("[bold]Starting LLM stack...[/bold]")
    _warn_if_low_memory()

    manager.ensure_ollama()
    console.print(f"  Ollama API:  http://localhost:{config.ollama_port}")

    if voice:
        manager.ensure_kokoro()
        console.print(f"  Kokoro TTS:  http://localhost:{config.kokoro_port}/v1")

    if whisper:
        manager.ensure_whisper()
        console.print(f"  Speaches STT: http://localhost:{config.whisper_port}")

    if image_gen:
        manager.ensure_comfyui(env_file=env_path)
        console.print(f"  ComfyUI:     http://localhost:{config.comfyui_port}")

    if webui:
        manager.ensure_webui(
            voice_enabled=voice,
            whisper_enabled=whisper,
            image_gen_enabled=image_gen,
            env_file=env_path,
        )
        console.print(f"  Open WebUI:  http://localhost:{config.webui_port}")

    if voice_agent:
        manager.ensure_voice_agent()
        console.print(f"  Voice agent: http://localhost:{config.voice_agent.port}")

    if n8n:
        manager.ensure_n8n(env_file=env_path)
        console.print(f"  n8n:         http://localhost:{config.n8n_port}")

    lan = _lan_ip()
    if lan:
        console.print("\n[bold]LAN access[/bold] (bound to 0.0.0.0):")
        console.print(f"  Ollama API:  http://{lan}:{config.ollama_port}")
        if voice:
            console.print(f"  Kokoro TTS:  http://{lan}:{config.kokoro_port}/v1")
        if whisper:
            console.print(f"  Speaches STT: http://{lan}:{config.whisper_port}")
        if image_gen:
            console.print(f"  ComfyUI:     http://{lan}:{config.comfyui_port}")
        if webui:
            console.print(f"  Open WebUI:  http://{lan}:{config.webui_port}")
        if voice_agent:
            console.print(f"  Voice agent: http://{lan}:{config.voice_agent.port}")
        if n8n:
            console.print(f"  n8n:         http://{lan}:{config.n8n_port}")

    console.print("\n[bold green]LLM stack is running.[/bold green]")


@llm_group.command("down")
@_stack_flags
@click.pass_context
def llm_down(
    ctx,
    webui: bool,
    voice: bool,
    no_voice: bool,
    whisper: bool,
    voice_agent: bool,
    n8n: bool,
    image_gen: bool,
    all_: bool,
    env_file: str | None,  # noqa: ARG001 — unused; present because _stack_flags adds it
):
    """Stop containers in the LLM stack.

    With no flags, stops only Ollama. Use stack flags or --all to stop
    additional stacks.
    """
    webui, voice, whisper, voice_agent, n8n, image_gen = _resolve_stacks(
        webui, voice, no_voice, whisper, voice_agent, n8n, image_gen, all_
    )
    manager = _get_manager(ctx)
    console.print("[bold]Stopping LLM stack...[/bold]")

    targets = [OLLAMA_CONTAINER]
    if webui:
        targets.append(WEBUI_CONTAINER)
    if voice:
        targets.append(KOKORO_CONTAINER)
    if whisper:
        targets.append(WHISPER_CONTAINER)
    if voice_agent:
        targets.append(VOICE_AGENT_CONTAINER)
    if n8n:
        targets.append(N8N_CONTAINER)
    if image_gen:
        targets.append(COMFYUI_CONTAINER)

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
    whisper: bool,
    voice_agent: bool,
    n8n: bool,
    image_gen: bool,
    all_: bool,
    env_file: str | None,  # noqa: ARG001 — unused; present because _stack_flags adds it
    wipe: bool,
    assume_yes: bool,
):
    """Remove LLM containers and (with --wipe) persistent data.

    With no stack flags, removes the base Ollama container only. Use stack
    flags or --all to also remove other stacks. --wipe additionally deletes
    named Docker volumes.
    """
    webui, voice, whisper, voice_agent, n8n, image_gen = _resolve_stacks(
        webui, voice, no_voice, whisper, voice_agent, n8n, image_gen, all_
    )
    manager = _get_manager(ctx)

    targets = [OLLAMA_CONTAINER]
    if webui:
        targets.append(WEBUI_CONTAINER)
    if voice:
        targets.append(KOKORO_CONTAINER)
    if whisper:
        targets.append(WHISPER_CONTAINER)
    if voice_agent:
        targets.append(VOICE_AGENT_CONTAINER)
    if n8n:
        targets.append(N8N_CONTAINER)
    if image_gen:
        targets.append(COMFYUI_CONTAINER)

    volumes: list[str] = []
    if wipe:
        volumes.append(OLLAMA_DATA_VOLUME)
        if webui:
            volumes.append(WEBUI_DATA_VOLUME)
        if whisper:
            volumes.append(WHISPER_DATA_VOLUME)
        if voice_agent:
            volumes.append(VOICE_AGENT_DATA_VOLUME)
        if n8n:
            volumes.append(N8N_DATA_VOLUME)
        if image_gen:
            volumes.append(COMFYUI_DATA_VOLUME)

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

    models = config.models_to_pull
    _validate_models_or_abort(*models)

    _pull_models(manager, models)

    console.print("\n[bold]Available models:[/bold]")
    output = manager.exec_in_ollama(["ollama", "list"])
    console.print(output)


@llm_group.command("models")
@click.option("--pulled", is_flag=True, help="Only show models that are downloaded in Ollama.")
@click.option(
    "--role",
    type=click.Choice(["chat", "coding"], case_sensitive=False),
    default=None,
    help="Filter by model role.",
)
@click.option("--uncensored", is_flag=True, help="Only show uncensored / abliterated models.")
@click.pass_context
def llm_models(ctx, pulled: bool, role: str | None, uncensored: bool):
    """Browse available LLM models with metadata.

    Shows a table of curated models cross-referenced against the active
    config and Ollama state. Each row shows the model tag, role, parameter
    count, disk size, uncensored marker, status, and description.

    \b
    Status meanings:
      config     in one of the 4 config slots or extra_models
      pulled     downloaded in Ollama but not in active config
      available  in catalog but not yet pulled
      untracked  in Ollama but not in the curated catalog
    """
    from ai_shell.models import MODEL_CATALOG, ModelInfo, classify_status

    manager = _get_manager(ctx)
    config = manager.config

    # Gather config tags (all 4 slots + extra_models)
    config_tags: set[str] = set(config.models_to_pull)

    # Gather pulled tags from Ollama (if running)
    pulled_tags: set[str] = set()
    ollama_running = manager.container_status(OLLAMA_CONTAINER) == "running"
    if ollama_running:
        output = manager.exec_in_ollama(["ollama", "list"])
        for line in output.splitlines()[1:]:  # skip header
            parts = line.split()
            if parts:
                # ollama list shows "name:tag" in first column
                pulled_tags.add(parts[0])

    # Build row list: catalog entries first, then untracked Ollama models
    rows: list[tuple[ModelInfo | None, str, str]] = []

    for info in MODEL_CATALOG:
        status = classify_status(info.tag, config_tags, pulled_tags)
        rows.append((info, info.tag, status))

    # Untracked models (in Ollama but not in catalog)
    catalog_tags = {m.tag for m in MODEL_CATALOG}
    for tag in sorted(pulled_tags - catalog_tags - config_tags):
        rows.append((None, tag, "untracked"))
    # Config tags that are pulled but not in catalog
    for tag in sorted(config_tags & pulled_tags - catalog_tags):
        rows.append((None, tag, "config"))

    # Apply filters
    if pulled:
        rows = [(i, t, s) for i, t, s in rows if t in pulled_tags]
    if role:
        rows = [(i, t, s) for i, t, s in rows if i is not None and i.role == role.lower()]
    if uncensored:
        rows = [(i, t, s) for i, t, s in rows if i is not None and i.uncensored]

    if not rows:
        console.print("[dim]No models match the given filters.[/dim]")
        return

    _STATUS_STYLE = {
        "config": "bold green",
        "pulled": "yellow",
        "available": "dim",
        "untracked": "dim italic",
    }

    console.print("[bold]LLM Model Catalog[/bold]\n")

    current_role: str | None = None
    for info, tag, status in rows:  # type: ignore[assignment]
        style = _STATUS_STYLE.get(status, "")

        if info is not None:
            # Group header when role changes
            if info.role != current_role:
                if current_role is not None:
                    console.print()
                current_role = info.role
                console.print(f"[bold underline]{info.role.upper()} models[/bold underline]")

            uncensored_mark = " [bold red](U)[/bold red]" if info.uncensored else ""
            status_text = f"[{style}]{status}[/{style}]"
            if status == "available":
                console.print(f"  [dim cyan]{tag}[/dim cyan]{uncensored_mark}  {status_text}")
                console.print(
                    f"    [dim]{info.params}  {info.size_gb:.0f} GB  {info.description}[/dim]"
                )
            else:
                console.print(f"  [cyan]{tag}[/cyan]{uncensored_mark}  {status_text}")
                console.print(f"    {info.params}  {info.size_gb:.0f} GB  {info.description}")
            if info.caveats and status == "config":
                console.print(f"    [dim yellow]caveat: {info.caveats}[/dim yellow]")
        else:
            # Untracked or config-but-not-cataloged model
            if current_role != "_untracked":
                if current_role is not None:
                    console.print()
                current_role = "_untracked"
                console.print("[bold underline]OTHER models (not in catalog)[/bold underline]")
            status_text = f"[{style}]{status}[/{style}]"
            console.print(f"  [dim cyan]{tag}[/dim cyan]  {status_text}")

    if not ollama_running:
        console.print(
            "\n[yellow]Ollama is not running — pulled status may be incomplete. "
            "Run [bold]ai-shell llm up[/bold] first.[/yellow]"
        )


@llm_group.command("unload")
@click.argument("model", required=False)
@click.pass_context
def llm_unload(ctx, model: str | None):
    """Unload running Ollama models from VRAM.

    With no argument, unloads every currently running model (parsed from
    ``ollama ps``). With a model name, unloads just that one. Useful
    before running ComfyUI / FLUX so both don't fight over GPU memory.
    """
    manager = _get_manager(ctx)
    if manager.container_status(OLLAMA_CONTAINER) != "running":
        console.print("[yellow]Ollama is not running — nothing to unload.[/yellow]")
        return

    if model:
        targets = [model]
    else:
        ps_output = manager.exec_in_ollama(["ollama", "ps"])
        targets = []
        for line in ps_output.splitlines()[1:]:  # skip header
            parts = line.split()
            if parts:
                targets.append(parts[0])
        if not targets:
            console.print("[dim]No models currently loaded.[/dim]")
            return

    for target in targets:
        console.print(f"  Unloading [cyan]{target}[/cyan]...")
        manager.exec_in_ollama(["ollama", "stop", target])
    console.print("[bold green]Done.[/bold green]")


@llm_group.command("setup")
@_stack_flags
@click.pass_context
def llm_setup(
    ctx,
    webui: bool,
    voice: bool,
    no_voice: bool,
    whisper: bool,
    voice_agent: bool,
    n8n: bool,
    image_gen: bool,
    all_: bool,
    env_file: str | None,
):
    """First-time setup: start stack, pull models, configure context.

    Accepts the same stack flags as ``llm up``. With no flags, sets up only
    the base Ollama container and pulls the configured primary/fallback models.
    """
    webui, voice, whisper, voice_agent, n8n, image_gen = _resolve_stacks(
        webui, voice, no_voice, whisper, voice_agent, n8n, image_gen, all_
    )
    env_path = Path(env_file) if env_file else None
    manager = _get_manager(ctx)
    config = manager.config

    models = config.models_to_pull
    _validate_models_or_abort(*models)

    console.print("[bold]Starting LLM stack...[/bold]")
    _warn_if_low_memory()
    manager.ensure_ollama()
    if voice:
        manager.ensure_kokoro()
    if whisper:
        manager.ensure_whisper()
    if image_gen:
        manager.ensure_comfyui(env_file=env_path)
    if webui:
        manager.ensure_webui(
            voice_enabled=voice,
            whisper_enabled=whisper,
            image_gen_enabled=image_gen,
            env_file=env_path,
        )
    if voice_agent:
        manager.ensure_voice_agent()
    if n8n:
        manager.ensure_n8n(env_file=env_path)

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

    _pull_models(manager, models)

    console.print("\n[bold green]============================================[/bold green]")
    console.print("[bold green] Setup complete![/bold green]")
    console.print(f"  Ollama API:  http://localhost:{config.ollama_port}")
    if voice:
        console.print(f"  Kokoro TTS:  http://localhost:{config.kokoro_port}/v1")
    if whisper:
        console.print(f"  Speaches STT: http://localhost:{config.whisper_port}")
    if image_gen:
        console.print(f"  ComfyUI:     http://localhost:{config.comfyui_port}")
    if webui:
        console.print(f"  Open WebUI:  http://localhost:{config.webui_port}")
    if voice_agent:
        console.print(f"  Voice agent: http://localhost:{config.voice_agent.port}")
    if n8n:
        console.print(f"  n8n:         http://localhost:{config.n8n_port}")
    console.print(f"\n  Primary chat:      {config.primary_chat_model}")
    console.print(f"  Secondary chat:    {config.secondary_chat_model}")
    console.print(f"  Primary coding:    {config.primary_coding_model}")
    console.print(f"  Secondary coding:  {config.secondary_coding_model}")
    if config.extra_models:
        console.print(f"  Extra models:      {', '.join(config.extra_models)}")
    console.print(f"  Context window:    {config.context_size} tokens")
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

    console.print("\n[bold]Speaches stack[/bold]")
    _render_container_row(manager, WHISPER_CONTAINER, "Speaches STT")

    console.print("\n[bold]Voice-agent stack[/bold]")
    _render_container_row(manager, VOICE_AGENT_CONTAINER, "Voice agent")

    console.print("\n[bold]n8n stack[/bold]")
    _render_container_row(manager, N8N_CONTAINER, "n8n")

    console.print("\n[bold]Image-gen stack[/bold]")
    _render_container_row(manager, COMFYUI_CONTAINER, "ComfyUI")

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
    _url("Speaches STT:", WHISPER_CONTAINER, f"http://localhost:{config.whisper_port}")
    _url(
        "  transcribe:",
        WHISPER_CONTAINER,
        f"http://localhost:{config.whisper_port}/v1/audio/transcriptions",
    )
    _url("Voice agent:", VOICE_AGENT_CONTAINER, f"http://localhost:{config.voice_agent.port}")
    _url("n8n:", N8N_CONTAINER, f"http://localhost:{config.n8n_port}")
    _url("ComfyUI:", COMFYUI_CONTAINER, f"http://localhost:{config.comfyui_port}")

    lan = _lan_ip()
    if lan:
        console.print("\n[bold]LAN access[/bold] (bound to 0.0.0.0):")
        console.print(f"  Ollama API:         http://{lan}:{config.ollama_port}")
        console.print(f"  Open WebUI:         http://{lan}:{config.webui_port}")
        console.print(f"  Kokoro TTS:         http://{lan}:{config.kokoro_port}/v1")
        console.print(f"  Speaches STT:       http://{lan}:{config.whisper_port}")
        console.print(f"  Voice agent:        http://{lan}:{config.voice_agent.port}")
        console.print(f"  n8n:                http://{lan}:{config.n8n_port}")
        console.print(f"  ComfyUI:            http://{lan}:{config.comfyui_port}")

    console.print("\n[bold]Configuration:[/bold]")
    console.print(f"  Primary chat:      {config.primary_chat_model}")
    console.print(f"  Secondary chat:    {config.secondary_chat_model}")
    console.print(f"  Primary coding:    {config.primary_coding_model}")
    console.print(f"  Secondary coding:  {config.secondary_coding_model}")
    if config.extra_models:
        console.print(f"  Extra models:      {', '.join(config.extra_models)}")
    console.print(f"  Context window:    {config.context_size} tokens")

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
            WHISPER_CONTAINER,
            VOICE_AGENT_CONTAINER,
            N8N_CONTAINER,
            COMFYUI_CONTAINER,
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
