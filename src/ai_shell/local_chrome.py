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
import socket
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

CHROME_DEBUG_HOST = "host.docker.internal"
DEFAULT_CHROME_DEBUG_PORT = 9222

MCP_CONFIG_FILENAME = "chrome-mcp.json"

# User-data-dir for the ai-shell debug Chrome profile (keeps it separate from
# the user's normal browsing).
_CHROME_PROFILE_DIR_NAME = "ai-debug-profile"

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

SETUP_INSTRUCTIONS = """\
Chrome could not be found or launched automatically, and the debug port \
is not reachable.

To fix, launch Chrome manually with these flags:

  chrome.exe --remote-debugging-port=9222 \\
    --remote-debugging-address=127.0.0.1 \\
    --remote-allow-origins=* \\
    --user-data-dir="%LOCALAPPDATA%\\Google\\Chrome\\ai-debug-profile"

Then re-run this command.
See README.md "Attaching to your Windows Chrome" for details."""


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


def _chrome_profile_dir() -> str:
    """Return the user-data-dir path for the ai-shell debug Chrome profile."""
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        return str(Path(local_app) / "Google" / "Chrome" / _CHROME_PROFILE_DIR_NAME)
    return str(Path.home() / ".config" / "google-chrome" / _CHROME_PROFILE_DIR_NAME)


def _find_free_port() -> int:
    """Find a free TCP port on the host by briefly binding to port 0."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def launch_chrome(port: int) -> bool:
    """Launch Chrome on the host with the debug port enabled.

    Returns ``True`` if Chrome was launched, ``False`` if Chrome could
    not be found.  The process is started detached so it outlives the CLI.
    """
    chrome_path = find_chrome()
    if chrome_path is None:
        return False

    profile_dir = _chrome_profile_dir()
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


def ensure_host_chrome(container_name: str) -> int:
    """Ensure Chrome is running with a debug port reachable from the container.

    1. Probe the default port (9222) -- if Chrome is already running, return it.
    2. Find a free port, launch Chrome on it, wait briefly for startup.
    3. Raise :class:`LocalChromeUnavailable` if Chrome can't be found or started.

    Returns the port number Chrome is listening on.
    """
    # Try the default port first -- user may have Chrome open already
    if probe_chrome_port(container_name, DEFAULT_CHROME_DEBUG_PORT):
        return DEFAULT_CHROME_DEBUG_PORT

    # Launch Chrome on a fresh port
    port = _find_free_port()
    logger.info(
        "Chrome not found on port %d, launching on port %d", DEFAULT_CHROME_DEBUG_PORT, port
    )

    if not launch_chrome(port):
        raise LocalChromeUnavailable(SETUP_INSTRUCTIONS)

    # Brief wait for Chrome to start (typically <2s)
    for attempt in range(5):
        time.sleep(1)
        if probe_chrome_port(container_name, port):
            logger.info("Chrome ready on port %d after %ds", port, attempt + 1)
            return port

    raise LocalChromeUnavailable(
        f"Chrome was launched on port {port} but the debug port did not become "
        "reachable within 5 seconds.\n\n"
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
