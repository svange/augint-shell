"""Local Chrome bridge for attaching chrome-devtools-mcp to a host browser.

Probes the Windows host's Chrome debug port from inside the container and
writes a minimal MCP config JSON that Claude Code can consume.

Chrome's DevTools Protocol rejects HTTP requests whose ``Host`` header is
not ``localhost`` or an IP address.  Because the MCP server inside the
container connects via ``host.docker.internal``, Chrome returns HTTP 500.
To work around this, we start a small Node.js TCP proxy inside the
container that forwards ``localhost:<port>`` to ``host.docker.internal:<port>``.
The MCP server then connects to ``localhost:<port>`` and Chrome sees a
``Host: localhost`` header.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import platform
import shutil
import subprocess
import time
from collections.abc import Callable
from hashlib import sha1
from http.client import HTTPConnection, HTTPException
from pathlib import Path

from ai_shell.defaults import unique_project_name

logger = logging.getLogger(__name__)

CHROME_DEBUG_HOST = "host.docker.internal"
CHROME_HOST_PROBE_TIMEOUT_SECONDS = 20.0
CHROME_CONTAINER_PROBE_TIMEOUT_SECONDS = 10.0
CHROME_PROBE_INTERVAL_SECONDS = 0.5
CHROME_DEBUG_PORT_RANGE_START = 40000
CHROME_DEBUG_PORT_RANGE_SIZE = 20000

MCP_CONFIG_FILENAME = "chrome-mcp.json"

# User-data-dir for ai-shell project-specific Chrome profiles (keeps them
# separate from the user's normal browsing and from other repos).
_CHROME_PROFILE_ROOT_DIR_NAME = "ai-shell"
# Slug prefix for account-scoped profiles so they can never collide with a
# project slug of the same name.
_ACCOUNT_PROFILE_PREFIX = "account-"

# Well-known Chrome install paths on Windows
_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
# macOS app bundles (system-wide, then per-user)
_CHROME_MAC_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]
# Linux: whatever is on PATH, Chrome first, then Chromium builds
_CHROME_LINUX_CANDIDATES = (
    "google-chrome",
    "google-chrome-stable",
    "google-chrome-beta",
    "chromium",
    "chromium-browser",
)
LOOPBACK = "127.0.0.1"

# Inline Node.js TCP proxy template -- forwards localhost:PORT to
# host.docker.internal:PORT so Chrome sees Host: localhost.
_NODE_PROXY_TEMPLATE = (
    "const net=require('net');"
    "net.createServer(c=>{{"
    "const s=net.connect({port},'host.docker.internal',()=>{{c.pipe(s);s.pipe(c)}});"
    "s.on('error',()=>c.destroy());c.on('error',()=>s.destroy())"
    "}}).listen({port},'127.0.0.1')"
)


class LocalChromeUnavailable(Exception):
    """Raised when the host Chrome debug port is not reachable."""


def find_chrome() -> str | None:
    """Locate the Chrome executable on the host.

    Windows: well-known install paths, then the per-user install. macOS: the
    app bundles. Linux: Chrome or Chromium on PATH. Returns the path as a
    string or ``None`` if Chrome is not found.
    """
    system = platform.system()
    if system == "Windows":
        for candidate in _CHROME_CANDIDATES:
            if Path(candidate).exists():
                return candidate
        # Fallback: per-user Chrome install
        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            user_chrome = Path(local_app) / "Google" / "Chrome" / "Application" / "chrome.exe"
            if user_chrome.exists():
                return str(user_chrome)
        return None
    if system == "Darwin":
        for candidate in _CHROME_MAC_CANDIDATES:
            path = Path(candidate).expanduser()
            if path.exists():
                return str(path)
        return None
    for name in _CHROME_LINUX_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


def chrome_bind_address(container_name: str) -> str:
    """Address Chrome's debug port must listen on so the container can reach it.

    Docker Desktop (Windows, macOS) forwards ``host.docker.internal`` to the
    host's loopback, so ``127.0.0.1`` works there. On a Linux host (Docker or
    podman) ``host.docker.internal`` resolves to the bridge gateway address,
    and a loopback-only listener is unreachable from containers, so Chrome
    binds to the address the container actually resolves for the host. That
    address is reachable from the host and its containers only.
    """
    if platform.system() != "Linux":
        return LOOPBACK
    result = subprocess.run(
        ["docker", "exec", container_name, "getent", "hosts", CHROME_DEBUG_HOST],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        candidate = result.stdout.split()[0]
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            logger.debug("Unexpected %s resolution %r", CHROME_DEBUG_HOST, candidate)
        else:
            return candidate
    logger.warning(
        "%s does not resolve inside %s; Chrome will bind to loopback, which Linux "
        "containers cannot reach. Docker needs `host-gateway` support (20.10+), podman 4.1+.",
        CHROME_DEBUG_HOST,
        container_name,
    )
    return LOOPBACK


def _project_slug(project_name: str, project_dir: str | Path | None = None) -> str:
    """Return a stable slug for project-scoped Chrome state."""
    if project_dir is not None:
        try:
            return unique_project_name(Path(project_dir), project_name)
        except (TypeError, ValueError):
            logger.debug("Falling back to project-name-only slug for %s", project_name)
    slug = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in project_name.lower())
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or "project"


def _chrome_slug(
    project_name: str,
    project_dir: str | Path | None = None,
    profile: str | None = None,
) -> str:
    """Slug that keys a Chrome instance: per account when *profile* is set, else per project.

    Logged-in browser state follows a person, not a repo, so a selected Claude
    account gets one Chrome (profile dir + debug port) shared by every project
    that uses that account. Two accounts never share a window.
    """
    if profile:
        slug = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in profile.lower())
        slug = "-".join(part for part in slug.split("-") if part)
        return _ACCOUNT_PROFILE_PREFIX + (slug or "default")
    return _project_slug(project_name, project_dir)


def _chrome_profile_dir(
    project_name: str,
    project_dir: str | Path | None = None,
    profile: str | None = None,
) -> str:
    """Return the user-data-dir path for a project's (or account's) ai-shell Chrome."""
    slug = _chrome_slug(project_name, project_dir, profile)
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        return str(Path(local_app) / "Google" / "Chrome" / _CHROME_PROFILE_ROOT_DIR_NAME / slug)
    return str(Path.home() / ".config" / "google-chrome" / _CHROME_PROFILE_ROOT_DIR_NAME / slug)


def _project_debug_port(
    project_name: str,
    project_dir: str | Path | None = None,
    profile: str | None = None,
) -> int:
    """Return a stable Chrome remote debugging port for the project or account."""
    slug = _chrome_slug(project_name, project_dir, profile)
    # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
    digest = sha1(slug.encode("utf-8"), usedforsecurity=False).hexdigest()
    return CHROME_DEBUG_PORT_RANGE_START + (int(digest[:8], 16) % CHROME_DEBUG_PORT_RANGE_SIZE)


def _build_setup_instructions(
    project_name: str,
    profile_dir: str,
    port: int,
    bind_address: str = LOOPBACK,
    proxy: str | None = None,
) -> str:
    """Return manual setup instructions for the project's Chrome profile."""
    binary = "chrome.exe" if platform.system() == "Windows" else "google-chrome"
    proxy_flag = f" \\\n    --proxy-server={proxy}" if proxy else ""
    return f"""\
Chrome could not be found or launched automatically, and the debug port \
is not reachable.

To fix, launch Chrome manually with these flags:

  {binary} --remote-debugging-port={port} \\
    --remote-debugging-address={bind_address} \\
    --remote-allow-origins=* \\
    --user-data-dir="{profile_dir}"{proxy_flag}

Then re-run this command for project '{project_name}'.
See README.md "Attaching to host Chrome" for details."""


def _proxy_args(proxy: str | None) -> list[str]:
    """Chrome flags that send its traffic through *proxy* (empty when unset).

    ``--proxy-server`` takes ``http://host:port``, ``socks5://host:port`` or
    a bare ``host:port``. Chrome never proxies loopback, so the DevTools
    bridge and the sign-in code flow are unaffected.
    """
    return [f"--proxy-server={proxy}"] if proxy else []


def _spawn_detached(args: list[str]) -> None:
    """Start *args* so the process outlives the CLI, on every platform."""
    if platform.system() == "Windows":
        creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
        subprocess.Popen(  # noqa: S603
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
    else:
        subprocess.Popen(  # noqa: S603
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )


def launch_chrome(
    port: int,
    *,
    project_name: str,
    project_dir: str | Path | None = None,
    profile: str | None = None,
    bind_address: str = LOOPBACK,
    proxy: str | None = None,
) -> bool:
    """Launch Chrome on the host with the debug port enabled.

    Returns ``True`` if Chrome was launched, ``False`` if Chrome could
    not be found.  The process is started detached so it outlives the CLI.
    With *proxy*, Chrome sends its traffic through that proxy server (a VPN
    container's HTTP proxy, for example).
    """
    chrome_path = find_chrome()
    if chrome_path is None:
        return False

    profile_dir = _chrome_profile_dir(project_name, project_dir, profile)
    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--remote-debugging-address={bind_address}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir}",
        # A fresh profile dir otherwise opens first-run / default-browser dialogs.
        "--no-first-run",
        "--no-default-browser-check",
        *_proxy_args(proxy),
    ]
    logger.info("Launching Chrome: %s", " ".join(args))
    _spawn_detached(args)
    return True


def chrome_profile_in_use(profile_dir: str | Path) -> bool:
    """True when a Chrome process holds *profile_dir* open.

    Chrome on Linux and macOS leaves a ``SingletonLock`` link in the profile
    while it runs and removes it on exit. Windows keeps its ``lockfile`` on
    disk, so there the answer is always ``False`` and the caller relies on
    the debug port probe instead.
    """
    if platform.system() == "Windows":
        return False
    return Path(profile_dir, "SingletonLock").is_symlink()


def launch_plain_chrome(
    *,
    project_name: str,
    project_dir: str | Path | None = None,
    profile: str | None = None,
    proxy: str | None = None,
    url: str | None = None,
) -> str:
    """Open the project's (or account's) ai-shell Chrome WITHOUT the debug port.

    Google refuses to sign in inside a browser that exposes a DevTools port
    ("This browser or app may not be secure"), so a Google (or Google SSO)
    sign-in has to happen in a plain window on the same profile directory.
    The cookies it leaves behind are what the debug-port Chrome reuses on
    the next ``--local-chrome`` launch. Returns the profile directory.

    Raises :class:`LocalChromeUnavailable` when Chrome is not installed, or
    when a Chrome already holds that profile: a second launch would only
    open a window inside the running (debug-port) process.
    """
    chrome_path = find_chrome()
    if chrome_path is None:
        raise LocalChromeUnavailable(
            "Chrome could not be found. Install Google Chrome or Chromium, or put it on PATH."
        )
    profile_dir = _chrome_profile_dir(project_name, project_dir, profile)
    port = _project_debug_port(project_name, project_dir, profile)
    if chrome_profile_in_use(profile_dir) or probe_host_chrome_port(port):
        raise LocalChromeUnavailable(
            f"A Chrome window already uses the profile {profile_dir}.\n"
            "Close every window of that Chrome (the one ai-shell opened with the "
            "DevTools port) and run this again: a second launch would open inside "
            "the running process, where Google still refuses the sign-in."
        )
    args = [
        chrome_path,
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        *_proxy_args(proxy),
    ]
    if url:
        args.append(url)
    logger.info("Launching plain Chrome: %s", " ".join(args))
    _spawn_detached(args)
    return profile_dir


def probe_chrome_port(container_name: str, port: int) -> bool:
    """Check whether a Chrome debug port is reachable from the container.

    Returns ``True`` if reachable, ``False`` otherwise.
    """
    probe_url = f"http://{CHROME_DEBUG_HOST}:{port}/json/version"
    args = [
        "docker",
        "exec",
        container_name,
        "curl",
        "-sS",
        "--max-time",
        "3",
        "-H",
        f"Host: localhost:{port}",
        probe_url,
    ]
    logger.debug("Probing Chrome debug port: %s", " ".join(args))
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        return False
    logger.info("Chrome debug port reachable: %s", result.stdout.strip()[:120])
    return True


def probe_host_chrome_port(port: int, host: str = LOOPBACK) -> bool:
    """Check whether a Chrome debug port is reachable on the host at *host*."""
    connection = HTTPConnection(host, port, timeout=2)
    try:
        connection.request("GET", "/json/version")
        response = connection.getresponse()
        return response.status == 200 and bool(response.read().strip())
    except (OSError, HTTPException):
        return False
    finally:
        connection.close()


def _wait_until_ready(
    probe_fn: Callable[..., bool],
    *args: object,
    timeout_seconds: float,
    interval_seconds: float = CHROME_PROBE_INTERVAL_SECONDS,
) -> bool:
    """Poll until a probe succeeds or the timeout expires."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        if probe_fn(*args):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(interval_seconds, remaining))


def ensure_host_chrome(
    container_name: str,
    *,
    project_name: str,
    project_dir: str | Path | None = None,
    profile: str | None = None,
    proxy: str | None = None,
) -> int:
    """Ensure Chrome is running with a debug port reachable from the container.

    Each project gets its own debug profile directory and a stable debug port,
    so different repos can keep separate logged-in Chrome instances alive.
    When *profile* is given (a Claude account), the profile and port are keyed
    by it instead, so one account keeps one browser across projects and two
    accounts never share one. *proxy* is handed to Chrome as
    ``--proxy-server`` when ai-shell has to launch it; a Chrome that is
    already running keeps whatever proxy it was started with.

    Returns the port number Chrome is listening on.
    """
    port = _project_debug_port(project_name, project_dir, profile)
    profile_dir = _chrome_profile_dir(project_name, project_dir, profile)

    if probe_chrome_port(container_name, port):
        return port

    logger.info("Chrome for project %s not found on port %d, launching it", project_name, port)

    bind_address = chrome_bind_address(container_name)
    if not launch_chrome(
        port,
        project_name=project_name,
        project_dir=project_dir,
        profile=profile,
        bind_address=bind_address,
        proxy=proxy,
    ):
        raise LocalChromeUnavailable(
            _build_setup_instructions(project_name, profile_dir, port, bind_address, proxy)
        )

    if not _wait_until_ready(
        probe_host_chrome_port,
        port,
        bind_address,
        timeout_seconds=CHROME_HOST_PROBE_TIMEOUT_SECONDS,
    ):
        raise LocalChromeUnavailable(
            f"Chrome was launched for project '{project_name}' on port {port}, but the "
            f"debug port did not open on {bind_address} within "
            f"{int(CHROME_HOST_PROBE_TIMEOUT_SECONDS)} seconds.\n\n"
            "If another ai-shell Chrome window for this project is already open, "
            "close it and retry."
        )

    if _wait_until_ready(
        probe_chrome_port,
        container_name,
        port,
        timeout_seconds=CHROME_CONTAINER_PROBE_TIMEOUT_SECONDS,
    ):
        logger.info("Chrome ready on port %d for project %s", port, project_name)
        return port

    raise LocalChromeUnavailable(
        f"Chrome is listening on {bind_address}:{port} for project '{project_name}', but the "
        "debug port did not become reachable from the dev container within "
        f"{int(CHROME_CONTAINER_PROBE_TIMEOUT_SECONDS)} seconds.\n\n"
        "Check that the container can reach the host via host.docker.internal "
        "(Docker Desktop on Windows/macOS; `host-gateway` on Linux Docker 20.10+ or podman 4.1+)."
    )


def start_chrome_proxy(container_name: str, port: int) -> None:
    """Start a TCP proxy inside the container: localhost:<port> -> host.docker.internal:<port>.

    Chrome rejects DevTools Protocol requests with a non-localhost Host
    header.  This proxy lets the MCP server connect to ``localhost:<port>``
    so Chrome sees ``Host: localhost``.

    The proxy runs as a detached background process via ``docker exec -d``.
    It's idempotent -- if the port is already in use (previous proxy still
    running), the new one fails silently and the existing one keeps working.
    """
    script = _NODE_PROXY_TEMPLATE.format(port=port)
    args = [
        "docker",
        "exec",
        "-d",
        container_name,
        "node",
        "-e",
        script,
    ]
    logger.debug("Starting Chrome proxy: %s", " ".join(args))
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning(
            "Chrome proxy start returned %d: %s", result.returncode, result.stderr.strip()
        )


CHROME_MCP_SERVER_NAME = "chrome-devtools"


def chrome_mcp_server_spec(port: int) -> dict[str, object]:
    """MCP server definition for chrome-devtools-mcp against the in-container proxy.

    Points at ``localhost:<port>`` (the proxy), not ``host.docker.internal``,
    because Chrome rejects the latter's Host header.
    """
    return {
        "command": "npx",
        "args": [
            "-y",
            "chrome-devtools-mcp@latest",
            "--browserUrl",
            f"http://localhost:{port}",
        ],
    }


def write_mcp_config(port: int, config_dir: Path | None = None) -> Path:
    """Write the chrome-devtools-mcp server config JSON.

    Returns the path to the written file. The file lives under
    ``~/.config/ai-shell/`` by default so it persists across sessions
    without polluting the project directory.
    """
    if config_dir is None:
        config_dir = Path.home() / ".config" / "ai-shell"
    config_dir.mkdir(parents=True, exist_ok=True)

    mcp_config = {"mcpServers": {CHROME_MCP_SERVER_NAME: chrome_mcp_server_spec(port)}}

    path = config_dir / MCP_CONFIG_FILENAME
    path.write_text(json.dumps(mcp_config, indent=2) + "\n", encoding="utf-8")
    logger.debug("Wrote MCP config: %s", path)
    return path
