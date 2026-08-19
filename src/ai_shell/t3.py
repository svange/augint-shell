"""T3 Code integration for dev containers.

`T3 Code <https://github.com/pingdotgg/t3code>`_ is a GUI (desktop, web and
mobile) that drives coding agents — Claude Code, Codex, OpenCode — through a
small HTTP/WebSocket server.  The server owns the workspace: it spawns the
agent processes, reads the git state and hosts the terminals.  So to control a
project from the T3 phone app, the *server* has to run where the project lives
— which, for ai-shell, is the per-project dev container.

That is what ``--t3`` does.  It starts ``t3 serve`` inside the dev container,
registers the project, and prints a pairing URL/QR pointing at the container's
published port on this machine's LAN address.

Two connection paths exist and both work through the same running server:

* **LAN pairing** (default, no account): the container port 3773 is published
  on a stable per-project host port, so a phone on the same network can reach
  it directly.  Pairing is a one-time token exchange; the device keeps a
  session afterwards.
* **T3 Connect** (optional, needs a T3 account): ``t3 connect link`` inside the
  container records the intent and the next ``t3 serve`` provisions the relay
  and launches a managed cloudflared tunnel.  That path is outbound-only, so it
  works from anywhere without the published port.

The server keeps running in the container after the local tool exits, which is
the point: the terminal session ends, remote control does not.
"""

from __future__ import annotations

import json
import logging
import shlex
import socket
import subprocess
import time
from typing import TYPE_CHECKING

from rich.console import Console

from ai_shell.defaults import T3_CONTAINER_PORT

if TYPE_CHECKING:
    from ai_shell.config import AiShellConfig
    from ai_shell.container import ContainerManager

logger = logging.getLogger(__name__)
console = Console(stderr=True)

#: npm package providing the ``t3`` binary.
T3_NPM_PACKAGE = "t3"

#: Unauthenticated descriptor endpoint — the readiness probe t3's own CLI uses.
T3_WELL_KNOWN_PATH = "/.well-known/t3/environment"

#: Where the detached server's stdout/stderr lands inside the container.
T3_LOG_PATH = "/var/log/ai-shell/t3-serve.log"

#: How long to wait for a freshly started server to answer the probe.
T3_READY_TIMEOUT = 90.0

#: npm install can be slow on a cold npm cache volume.
T3_INSTALL_TIMEOUT = 900


class T3Error(Exception):
    """T3 Code could not be started or paired inside the dev container."""


def _exec(
    container_name: str,
    args: list[str],
    *,
    extra_env: dict[str, str] | None = None,
    timeout: float | None = 60,
) -> subprocess.CompletedProcess[str]:
    """Run a command in *container_name* and capture its output."""
    cmd = ["docker", "exec"]
    for key, value in (extra_env or {}).items():
        cmd.extend(["-e", f"{key}={value}"])
    cmd.append(container_name)
    cmd.extend(args)
    logger.debug("t3 exec: %s", " ".join(args))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _login_shell(script: str) -> list[str]:
    """Wrap *script* so it runs with the container's login PATH.

    ``.bashrc`` returns early for non-interactive shells, so this picks up
    ``/etc/profile.d`` PATH additions without any MOTD noise polluting the
    output we parse.
    """
    return ["bash", "-lc", script]


def _t3(
    container_name: str,
    argv: list[str],
    *,
    timeout: float | None = 60,
) -> subprocess.CompletedProcess[str]:
    """Run a ``t3`` subcommand through the login shell so PATH is resolved."""
    return _exec(container_name, _login_shell(shlex.join(["t3", *argv])), timeout=timeout)


def ensure_cli(container_name: str) -> None:
    """Make sure the ``t3`` binary exists in the container.

    Images from before T3 support shipped don't have it, so install on demand
    rather than forcing an image pull.  Newer images bake it in and this is a
    single cheap ``command -v``.
    """
    if _exec(container_name, _login_shell("command -v t3"), timeout=30).returncode == 0:
        return

    console.print("[dim]Installing the T3 Code CLI (npm install -g t3)...[/dim]")
    result = _exec(
        container_name,
        _login_shell(f"npm install -g {shlex.quote(T3_NPM_PACKAGE)}"),
        timeout=T3_INSTALL_TIMEOUT,
    )
    if result.returncode != 0:
        raise T3Error(
            "Failed to install the T3 Code CLI in the dev container.\n"
            f"  npm said: {(result.stderr or result.stdout).strip()[-500:]}"
        )


def server_running(container_name: str, port: int = T3_CONTAINER_PORT) -> bool:
    """Return True when a T3 Code server answers on *port* in the container."""
    result = _exec(
        container_name,
        [
            "curl",
            "-fsS",
            "-m",
            "3",
            f"http://127.0.0.1:{port}{T3_WELL_KNOWN_PATH}",
        ],
        timeout=15,
    )
    return result.returncode == 0


def start_server(
    container_name: str,
    workdir: str,
    *,
    port: int = T3_CONTAINER_PORT,
    extra_env: dict[str, str] | None = None,
) -> None:
    """Start ``t3 serve`` detached inside the container.

    Bound to ``0.0.0.0`` so the published Docker port actually reaches it, and
    pinned to *port* because t3's web mode otherwise scans upward from 3773 for
    a free port — which would land outside the published mapping.

    *extra_env* is the same environment an interactive tool launch gets, so the
    agents T3 spawns see the same credentials and settings.
    """
    inner = (
        f"mkdir -p $(dirname {shlex.quote(T3_LOG_PATH)}) && "
        f"exec t3 serve --host 0.0.0.0 --port {port} {shlex.quote(workdir)} "
        f">>{shlex.quote(T3_LOG_PATH)} 2>&1"
    )
    cmd = ["docker", "exec", "-d"]
    for key, value in (extra_env or {}).items():
        cmd.extend(["-e", f"{key}={value}"])
    cmd.append(container_name)
    cmd.extend(_login_shell(inner))
    logger.debug("t3 serve: %s", inner)
    subprocess.run(cmd, check=True, capture_output=True)


def wait_until_ready(
    container_name: str,
    *,
    port: int = T3_CONTAINER_PORT,
    timeout: float = T3_READY_TIMEOUT,
) -> bool:
    """Poll the descriptor endpoint until the server answers or *timeout*."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server_running(container_name, port):
            return True
        time.sleep(1.0)
    return False


def server_log_tail(container_name: str, lines: int = 20) -> str:
    """Return the tail of the detached server's log, for failure reporting."""
    result = _exec(
        container_name,
        _login_shell(f"tail -n {lines} {shlex.quote(T3_LOG_PATH)} 2>/dev/null || true"),
        timeout=15,
    )
    return (result.stdout or "").strip()


def add_project(container_name: str, workdir: str, title: str) -> None:
    """Register *workdir* as a T3 project.

    ``t3 serve`` deliberately does not auto-create a project for its cwd, so
    without this the paired device connects to an empty environment.  Adding an
    already-known project is an error in t3, which is fine — it means the
    project survived from a previous run.
    """
    result = _t3(container_name, ["project", "add", workdir, "--title", title])
    if result.returncode != 0:
        logger.debug(
            "t3 project add returned %s (already registered?): %s",
            result.returncode,
            (result.stderr or result.stdout).strip(),
        )


def mint_pairing_token(container_name: str) -> str | None:
    """Mint a one-time pairing token for the running server.

    ``t3 pair`` prints a pairing URL built from the container's own address,
    which no phone can reach; only the token is portable, so that is all we
    take.  The URL is rebuilt against the published host port by the caller.
    """
    result = _t3(container_name, ["pair"])
    if result.returncode != 0:
        logger.debug("t3 pair failed: %s", (result.stderr or result.stdout).strip())
        return None
    for line in (result.stdout or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("Token:"):
            token = stripped.split(":", 1)[1].strip()
            if token:
                return token
    return None


def connect_status(container_name: str) -> dict[str, object] | None:
    """Return ``t3 connect status --json`` as a dict, or None when unavailable.

    The connect command group is absent from builds without cloud
    configuration, and present-but-unauthorized otherwise, so a failure here is
    informational only.
    """
    result = _t3(container_name, ["connect", "status", "--json"], timeout=30)
    if result.returncode != 0:
        return None
    try:
        parsed = json.loads(result.stdout)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def host_lan_ip() -> str | None:
    """Best-effort LAN address of the machine running ai-shell.

    A UDP socket sends nothing on ``connect``; it just makes the kernel pick
    the interface it would route through, which is the address a phone on the
    same network can reach.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.5)
            sock.connect(("8.8.8.8", 80))
            address: str = sock.getsockname()[0]
    except OSError:
        return None
    return address or None


def render_qr(data: str, border: int = 2) -> str | None:
    """Render *data* as a half-block QR code, or None if segno is missing.

    Two matrix rows per text row, matching how t3's own CLI draws its codes so
    the two outputs look the same in a terminal.
    """
    try:
        import segno
    except ImportError:  # pragma: no cover - segno is a declared dependency
        return None

    matrix = [bytearray(row) for row in segno.make(data, error="m").matrix]
    size = len(matrix)

    def dark(x: int, y: int) -> bool:
        return 0 <= x < size and 0 <= y < size and bool(matrix[y][x])

    rows: list[str] = []
    for y in range(-border, size + border, 2):
        row = ""
        for x in range(-border, size + border):
            top, bottom = dark(x, y), dark(x, y + 1)
            row += "█" if top and bottom else "▀" if top else "▄" if bottom else " "
        rows.append(row)
    return "\n".join(rows)


def _published_host_port(manager: ContainerManager, container_name: str, port: int) -> int | None:
    """Host port bound to *port*, read from the live container."""
    from docker.errors import DockerException

    try:
        ports = manager.container_ports(container_name)
    except DockerException:
        return None
    binding = (ports or {}).get(f"{port}/tcp")
    if not binding:
        return None
    try:
        return int(binding.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None


def _print_connect_status(status: dict[str, object] | None) -> None:
    """Print the T3 Connect line, which only matters once linked."""
    if status is None:
        return
    if not status.get("desired"):
        console.print(
            "  [dim]T3 Connect: off — run [/dim][cyan]t3 connect link --headless[/cyan]"
            "[dim] inside [/dim][cyan]ai-shell shell[/cyan][dim] "
            "to reach this project from outside the LAN.[/dim]"
        )
        return
    relay = status.get("relayUrl")
    if status.get("linked") and relay:
        console.print(f"  [green]T3 Connect: linked[/green] [dim]({relay})[/dim]")
    else:
        console.print("  [yellow]T3 Connect: enabled, waiting for the relay link[/yellow]")


def attach(
    manager: ContainerManager,
    container_name: str,
    config: AiShellConfig,
    exec_env: dict[str, str] | None = None,
    *,
    port: int = T3_CONTAINER_PORT,
) -> None:
    """Start (or reuse) the T3 Code server and print pairing details.

    Idempotent: re-running against a live server skips the start and just mints
    a fresh pairing token, which is how you pair a second device.
    """
    ensure_cli(container_name)

    workdir = f"/root/projects/{config.project_name}"

    if server_running(container_name, port):
        console.print(f"[dim]T3 Code server already running in {container_name}.[/dim]")
    else:
        console.print(f"[bold]Starting the T3 Code server in {container_name}...[/bold]")
        start_server(container_name, workdir, port=port, extra_env=exec_env)
        with console.status("[bold]Waiting for T3 Code to come up...[/bold]", spinner="dots"):
            ready = wait_until_ready(container_name, port=port)
        if not ready:
            tail = server_log_tail(container_name)
            raise T3Error(
                f"The T3 Code server did not come up on port {port} within "
                f"{int(T3_READY_TIMEOUT)}s.\n"
                f"  Log ({T3_LOG_PATH}):\n{tail or '  (empty)'}"
            )

    add_project(container_name, workdir, config.project_name)

    host_port = _published_host_port(manager, container_name, port)
    token = mint_pairing_token(container_name)

    console.print("[bold]T3 Code[/bold]")
    console.print(f"  [dim]Project:[/dim] {config.project_name} [dim]({workdir})[/dim]")

    if host_port is None:
        console.print(
            f"  [yellow]Container port {port} is not published, so this server cannot be "
            "paired over the LAN.[/yellow]"
        )
        console.print(
            "  [yellow]This container predates T3 support — recreate it with "
            "[/yellow][cyan]ai-shell manage clean[/cyan][yellow] and rerun.[/yellow]"
        )
    elif token is None:
        console.print(
            "  [yellow]Could not mint a pairing token; the server is up at "
            f"http://localhost:{host_port} — pair from the desktop app instead.[/yellow]"
        )
    else:
        lan_ip = host_lan_ip()
        pair_host = lan_ip or "localhost"
        pairing_url = f"http://{pair_host}:{host_port}/pair#token={token}"
        console.print(
            f"  [dim]Server:[/dim]  http://localhost:{host_port} [dim](this machine)[/dim]"
        )
        console.print(f"  [green bold]Pair:[/green bold]    {pairing_url}")
        console.print(f"  [dim]Host:[/dim]    http://{pair_host}:{host_port}")
        console.print(f"  [dim]Token:[/dim]   {token}")
        qr = render_qr(pairing_url)
        if qr:
            console.print()
            # Printed raw: rich would try to interpret the block art as markup.
            print(qr)
        if lan_ip is None:
            console.print(
                "  [yellow]Could not determine this machine's LAN address; the pairing URL "
                "only works from this machine.[/yellow]"
            )

    _print_connect_status(connect_status(container_name))
    console.print(
        "  [dim]The server keeps running in the container after this session exits.[/dim]"
    )
