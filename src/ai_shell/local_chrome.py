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

import json
import logging
import os
import platform
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

# Well-known Chrome install paths on Windows
_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

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
    """Locate chrome.exe on the Windows host.

    Checks well-known install paths.  Returns the path as a string
    or ``None`` if Chrome is not found.
    """
    if platform.system() != "Windows":
        return None
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


def _chrome_profile_dir(project_name: str, project_dir: str | Path | None = None) -> str:
    """Return the user-data-dir path for a project's ai-shell debug Chrome."""
    slug = _project_slug(project_name, project_dir)
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        return str(Path(local_app) / "Google" / "Chrome" / _CHROME_PROFILE_ROOT_DIR_NAME / slug)
    return str(Path.home() / ".config" / "google-chrome" / _CHROME_PROFILE_ROOT_DIR_NAME / slug)


def _project_debug_port(project_name: str, project_dir: str | Path | None = None) -> int:
    """Return a stable per-project Chrome remote debugging port."""
    slug = _project_slug(project_name, project_dir)
    digest = (
        sha1(slug.encode("utf-8"), usedforsecurity=False).hexdigest()
    )  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
    return CHROME_DEBUG_PORT_RANGE_START + (int(digest[:8], 16) % CHROME_DEBUG_PORT_RANGE_SIZE)


def _build_setup_instructions(project_name: str, profile_dir: str, port: int) -> str:
    """Return manual setup instructions for the project's Chrome profile."""
    return f"""\
Chrome could not be found or launched automatically, and the debug port \
is not reachable.

To fix, launch Chrome manually with these flags:

  chrome.exe --remote-debugging-port={port} \\
    --remote-debugging-address=127.0.0.1 \\
    --remote-allow-origins=* \\
    --user-data-dir="{profile_dir}"

Then re-run this command for project '{project_name}'.
See README.md "Attaching to your Windows Chrome" for details."""


def launch_chrome(
    port: int,
    *,
    project_name: str,
    project_dir: str | Path | None = None,
) -> bool:
    """Launch Chrome on the host with the debug port enabled.

    Returns ``True`` if Chrome was launched, ``False`` if Chrome could
    not be found.  The process is started detached so it outlives the CLI.
    """
    chrome_path = find_chrome()
    if chrome_path is None:
        return False

    profile_dir = _chrome_profile_dir(project_name, project_dir)
    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir}",
    ]
    logger.info("Launching Chrome: %s", " ".join(args))

    # Start detached so Chrome outlives the CLI process.
    creation_flags = 0
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
    return True


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


def probe_host_chrome_port(port: int) -> bool:
    """Check whether a Chrome debug port is reachable on the host."""
    connection = HTTPConnection("127.0.0.1", port, timeout=2)
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
) -> int:
    """Ensure Chrome is running with a debug port reachable from the container.

    Each project gets its own debug profile directory and a stable debug port,
    so different repos can keep separate logged-in Chrome instances alive.

    Returns the port number Chrome is listening on.
    """
    port = _project_debug_port(project_name, project_dir)
    profile_dir = _chrome_profile_dir(project_name, project_dir)

    if probe_chrome_port(container_name, port):
        return port

    logger.info("Chrome for project %s not found on port %d, launching it", project_name, port)

    if not launch_chrome(port, project_name=project_name, project_dir=project_dir):
        raise LocalChromeUnavailable(_build_setup_instructions(project_name, profile_dir, port))

    if not _wait_until_ready(
        probe_host_chrome_port,
        port,
        timeout_seconds=CHROME_HOST_PROBE_TIMEOUT_SECONDS,
    ):
        raise LocalChromeUnavailable(
            f"Chrome was launched for project '{project_name}' on port {port}, but the "
            f"debug port did not open on localhost within "
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
        f"Chrome is listening on localhost:{port} for project '{project_name}', but the "
        "debug port did not become reachable from the dev container within "
        f"{int(CHROME_CONTAINER_PROBE_TIMEOUT_SECONDS)} seconds.\n\n"
        "Check that Docker Desktop can reach the host via host.docker.internal."
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


def write_mcp_config(port: int, config_dir: Path | None = None) -> Path:
    """Write the chrome-devtools-mcp server config JSON.

    Returns the path to the written file. The file lives under
    ``~/.config/ai-shell/`` by default so it persists across sessions
    without polluting the project directory.

    The config points at ``localhost:<port>`` (the in-container proxy),
    not ``host.docker.internal:<port>``, because Chrome rejects the latter.
    """
    if config_dir is None:
        config_dir = Path.home() / ".config" / "ai-shell"
    config_dir.mkdir(parents=True, exist_ok=True)

    mcp_config = {
        "mcpServers": {
            "chrome-devtools": {
                "command": "npx",
                "args": [
                    "-y",
                    "chrome-devtools-mcp@latest",
                    "--browserUrl",
                    f"http://localhost:{port}",
                ],
            }
        }
    }

    path = config_dir / MCP_CONFIG_FILENAME
    path.write_text(json.dumps(mcp_config, indent=2) + "\n", encoding="utf-8")
    logger.debug("Wrote MCP config: %s", path)
    return path
