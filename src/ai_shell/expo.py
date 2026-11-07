"""Expo dev server integration for dev containers.

``ai-shell claude --expo`` (and the same flag on the other tool commands)
starts ``npx expo start --tunnel`` inside the per-project dev container and
prints the tunnel URL as a QR code *before* the agent takes over the terminal,
so a phone can be pointed at the running app up front.  Auto-detection starts
it for any directory that actually looks like an Expo app, which is the common
case for these repos.

Why the tunnel is the default — and the only mode implemented:

* ngrok dials **outbound** from the container to Expo's ngrok edge, so the
  phone reaches ``https://<subdomain>.exp.direct`` without any published port.
  ai-shell's dev ports are hash-assigned into 10000-39999 rather than mapped
  identity, so a LAN URL would advertise the container's own ``:8081`` and be
  unreachable; tunnelling sidesteps the whole problem.
* No Expo account is needed.  ``@expo/cli`` connects with **its own** ngrok
  auth token and builds the hostname as
  ``{randomness}-{username}-{port}.exp.direct``, where the username falls back
  to ``anonymous`` when nobody is logged in.  Logging in only matters for EAS
  (``build``/``update``/``submit``).
* ``randomness`` is persisted in ``.expo/settings.json`` *in the project
  directory*, which is bind-mounted, so the tunnel URL — and therefore the QR
  code — is stable across restarts and container recreations.  Nothing needs
  to be pinned with ``EXPO_TUNNEL_SUBDOMAIN``.

One sharp edge worth knowing: if ``EXPO_TOKEN`` holds a **robot** token, the
Expo CLI refuses to open a tunnel at all (``NGROK_ROBOT``).  That failure is
detected in the server log and reported with the fix.

Like the T3 server, the dev server is started detached and outlives the tool
session — the terminal goes away, the app on the phone keeps reloading.
"""

from __future__ import annotations

import json
import logging
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

from ai_shell.defaults import EXPO_METRO_PORT
from ai_shell.qr import render_qr

if TYPE_CHECKING:
    from ai_shell.config import AiShellConfig
    from ai_shell.container import ContainerManager

logger = logging.getLogger(__name__)
console = Console(stderr=True)

#: npm package providing the ngrok binding the Expo CLI loads for tunnels.
#: ``NgrokResolver`` prefers a global install and does not prompt for one on a
#: non-TTY, so it has to be present before ``expo start --tunnel`` runs.
EXPO_NGROK_PACKAGE = "@expo/ngrok@^4.1.0"

#: Where the detached dev server's stdout/stderr lands inside the container.
EXPO_LOG_PATH = "/var/log/ai-shell/expo-start.log"

#: How long to wait for the tunnel URL to show up in the log.  ngrok
#: negotiation on a cold start is the slow part, not Metro.
EXPO_READY_TIMEOUT = 180.0

#: npm install can be slow on a cold npm cache volume.
EXPO_INSTALL_TIMEOUT = 900

#: App-config filenames that mark a directory as an Expo app.  ``app.json`` is
#: only counted when it actually carries an ``expo`` key — plenty of unrelated
#: projects ship an ``app.json``.
_APP_CONFIG_FILES = (
    "app.config.ts",
    "app.config.js",
    "app.config.mjs",
    "app.config.cjs",
    "app.config.json",
)

#: The tunnel URL as the Expo CLI prints it.  Both schemes are matched because
#: the CLI logs the ``exp://`` deep link and the ``https://`` origin.
_TUNNEL_URL_RE = re.compile(r"\b(?:exp|https)://[A-Za-z0-9._-]+\.exp\.direct(?::\d+)?\b")


class ExpoError(Exception):
    """The Expo dev server could not be started inside the dev container."""


@dataclass(frozen=True)
class ExpoProject:
    """What the host filesystem says about the project at *project_dir*."""

    project_dir: Path
    has_dependency: bool
    app_config: str | None

    @property
    def is_app(self) -> bool:
        """True when this looks like a real Expo app, not just an expo dep.

        Both signals are required for *auto-detection*: an ``expo`` dependency
        alone also describes Expo libraries and config plugins, which have
        nothing to serve.  ``--expo`` only requires the dependency.
        """
        return self.has_dependency and self.app_config is not None


def detect(project_dir: Path | str) -> ExpoProject:
    """Inspect *project_dir* for the two Expo app signals.

    A directory that cannot be inspected at all is simply not an Expo app —
    detection never fails a launch.
    """
    try:
        project_dir = Path(project_dir)
    except TypeError:
        logger.debug("Not a usable project directory: %r", project_dir)
        return ExpoProject(project_dir=Path(), has_dependency=False, app_config=None)

    package_json = project_dir / "package.json"
    has_dependency = False
    if package_json.is_file():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.debug("Could not read %s: %s", package_json, exc)
            data = {}
        if isinstance(data, dict):
            for section in ("dependencies", "devDependencies"):
                deps = data.get(section)
                if isinstance(deps, dict) and "expo" in deps:
                    has_dependency = True
                    break

    app_config: str | None = None
    app_json = project_dir / "app.json"
    if app_json.is_file():
        try:
            parsed = json.loads(app_json.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.debug("Could not read %s: %s", app_json, exc)
            parsed = None
        if isinstance(parsed, dict) and "expo" in parsed:
            app_config = "app.json"
    if app_config is None:
        for name in _APP_CONFIG_FILES:
            if (project_dir / name).is_file():
                app_config = name
                break

    return ExpoProject(
        project_dir=project_dir,
        has_dependency=has_dependency,
        app_config=app_config,
    )


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
    logger.debug("expo exec: %s", " ".join(args))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _login_shell(script: str) -> list[str]:
    """Wrap *script* so it runs with the container's login PATH."""
    return ["bash", "-lc", script]


def dependency_installed(container_name: str, workdir: str) -> bool:
    """True when ``expo`` resolves from *workdir* inside the container.

    The check has to run in the container: ``node_modules`` is overlaid with a
    per-project named volume, so the host's copy says nothing about what the
    container can actually resolve.  Node resolution (rather than a
    ``node_modules/expo`` stat) also covers monorepos that hoist.
    """
    script = f"cd {shlex.quote(workdir)} && node -e \"require.resolve('expo/package.json')\""
    return _exec(container_name, _login_shell(script), timeout=60).returncode == 0


def ensure_ngrok(container_name: str) -> None:
    """Install ``@expo/ngrok`` globally if it is not already there.

    The Expo CLI resolves it with ``prefersGlobalInstall`` and, on the second
    pass, with prompting and auto-install both disabled — so without this the
    tunnel just asserts on a detached (non-TTY) start.
    """
    probe = 'test -d "$(npm root -g)/@expo/ngrok"'
    if _exec(container_name, _login_shell(probe), timeout=60).returncode == 0:
        return

    console.print(
        f"[dim]Installing the Expo tunnel dependency (npm install -g {EXPO_NGROK_PACKAGE})...[/dim]"
    )
    result = _exec(
        container_name,
        _login_shell(f"npm install -g {shlex.quote(EXPO_NGROK_PACKAGE)}"),
        timeout=EXPO_INSTALL_TIMEOUT,
    )
    if result.returncode != 0:
        raise ExpoError(
            "Failed to install @expo/ngrok in the dev container, so the tunnel "
            "cannot be opened.\n"
            f"  npm said: {(result.stderr or result.stdout).strip()[-500:]}"
        )


def server_running(container_name: str) -> bool:
    """True when an Expo dev server process is already up in the container."""
    result = _exec(container_name, ["pgrep", "-f", "expo start"], timeout=15)
    return result.returncode == 0


def server_log(container_name: str, lines: int = 200) -> str:
    """Return the tail of the detached server's log."""
    result = _exec(
        container_name,
        _login_shell(f"tail -n {lines} {shlex.quote(EXPO_LOG_PATH)} 2>/dev/null || true"),
        timeout=15,
    )
    return (result.stdout or "").strip()


def tunnel_url(container_name: str) -> str | None:
    """Most recent tunnel URL in the server log, normalized to ``exp://``.

    Expo Go and dev clients open the ``exp://`` deep link; the ``https://``
    origin in the log is the same host.
    """
    matches: list[str] = _TUNNEL_URL_RE.findall(server_log(container_name))
    if not matches:
        return None
    url = matches[-1]
    if url.startswith("https://"):
        url = "exp://" + url[len("https://") :]
    return url


def start_server(
    container_name: str,
    workdir: str,
    *,
    port: int = EXPO_METRO_PORT,
    extra_env: dict[str, str] | None = None,
) -> None:
    """Start ``expo start --tunnel`` detached inside the container.

    The log is truncated on each fresh start so :func:`tunnel_url` can never
    hand back a URL from a previous run's tunnel.
    """
    inner = (
        f"mkdir -p $(dirname {shlex.quote(EXPO_LOG_PATH)}) && "
        f"cd {shlex.quote(workdir)} && "
        f"exec npx expo start --tunnel --port {port} "
        f"</dev/null >{shlex.quote(EXPO_LOG_PATH)} 2>&1"
    )
    env = dict(extra_env or {})
    # We render our own QR from the parsed URL, so the CLI's copy is just log
    # noise that the URL regex would have to scan past.
    env["EXPO_NO_QR_CODE"] = "1"
    env["BROWSER"] = "none"

    cmd = ["docker", "exec", "-d"]
    for key, value in env.items():
        cmd.extend(["-e", f"{key}={value}"])
    cmd.append(container_name)
    cmd.extend(_login_shell(inner))
    logger.debug("expo start: %s", inner)
    subprocess.run(cmd, check=True, capture_output=True)


def wait_for_tunnel(
    container_name: str,
    *,
    timeout: float = EXPO_READY_TIMEOUT,
) -> str | None:
    """Poll the log until the tunnel URL appears, or *timeout* elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        url = tunnel_url(container_name)
        if url:
            return url
        time.sleep(1.0)
    return None


def _startup_failure(log: str) -> str | None:
    """Translate a known fatal log signature into an actionable message."""
    if "NGROK_ROBOT" in log or "Cannot use ngrok with a robot user" in log:
        return (
            "EXPO_TOKEN is a robot token, and the Expo CLI refuses to open a "
            "tunnel for robot users.\n"
            "  Use a personal access token, or unset EXPO_TOKEN for this project."
        )
    if "@expo/ngrok" in log and "install" in log.lower():
        return (
            "The Expo CLI could not load @expo/ngrok.\n"
            "  Install it in the container: run 'ai-shell shell' and then "
            "'npm install -g @expo/ngrok'."
        )
    return None


def attach(
    manager: ContainerManager,
    container_name: str,
    config: AiShellConfig,
    exec_env: dict[str, str] | None = None,
    *,
    port: int = EXPO_METRO_PORT,
    explicit: bool = False,
) -> None:
    """Start (or reuse) the Expo dev server and print the tunnel URL/QR.

    *explicit* marks a user-requested ``--expo``: preconditions that are
    silently skipped during auto-detection become hard errors instead, because
    the user asked for something that cannot be delivered.

    Idempotent: against a live server this just re-prints the QR, which is how
    a second device gets pointed at the same app.
    """
    project = detect(config.project_dir)

    if not project.has_dependency:
        if explicit:
            raise ExpoError(
                f"{config.project_dir} has no 'expo' dependency in package.json, "
                "so there is no Expo app to start."
            )
        return
    if not project.is_app and not explicit:
        logger.debug("Expo dependency without an app config in %s; skipping", config.project_dir)
        return

    workdir = f"/root/projects/{config.project_name}"

    if not dependency_installed(container_name, workdir):
        message = (
            "Expo is in package.json but is not installed in the dev container "
            "(node_modules is a container-local volume, not the host's).\n"
            "  Install inside the container first: run 'ai-shell shell' "
            "and then 'npm install'."
        )
        if explicit:
            raise ExpoError(message)
        console.print(f"[yellow]Skipping the Expo dev server: {message}[/yellow]")
        return

    reused = server_running(container_name)
    if reused:
        console.print(f"[dim]Expo dev server already running in {container_name}.[/dim]")
        url = tunnel_url(container_name)
    else:
        ensure_ngrok(container_name)
        console.print(f"[bold]Starting the Expo dev server in {container_name}...[/bold]")
        start_server(container_name, workdir, port=port, extra_env=exec_env)
        with console.status("[bold]Opening the Expo tunnel...[/bold]", spinner="dots"):
            url = wait_for_tunnel(container_name)

    if url is None:
        log = server_log(container_name)
        if reused:
            # Something is serving, but no tunnel URL was ever logged — most
            # likely an `expo start` someone launched by hand without --tunnel.
            reason = (
                "An Expo dev server is already running in the container but has "
                "no tunnel URL, so there is nothing a phone can reach.\n"
                "  Stop it (pkill -f 'expo start' in the container) and rerun to "
                "get a tunnelled one."
            )
        else:
            reason = (
                _startup_failure(log)
                or f"The Expo tunnel did not come up within {int(EXPO_READY_TIMEOUT)}s."
            )
        raise ExpoError(reason + f"\n  Log ({EXPO_LOG_PATH}):\n{log[-1500:] or '  (empty)'}")

    host_port = _published_host_port(manager, container_name, port)

    console.print("[bold]Expo[/bold]")
    console.print(f"  [dim]Project:[/dim] {config.project_name} [dim]({workdir})[/dim]")
    console.print(f"  [green bold]Scan:[/green bold]    {url}")
    if host_port is not None:
        console.print(
            f"  [dim]Metro:[/dim]   http://localhost:{host_port} [dim](this machine)[/dim]"
        )
    console.print(f"  [dim]Log:[/dim]     docker exec {container_name} tail -f {EXPO_LOG_PATH}")

    qr = render_qr(url)
    if qr:
        console.print()
        console.print(qr)
        console.print()


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
