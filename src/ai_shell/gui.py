"""Host GUI display forwarding (WSLg, native X11/Wayland, and X11 TCP fallback).

Resolves the bind mounts, device passthroughs (e.g. ``/dev/dxg`` for WSLg
GPU rendering), and environment variables needed so GUI applications inside
an ``augint-shell`` dev container (``xterm``, ``wireshark``, headed Chrome /
Playwright, GTK/Qt apps) appear as windows on the host desktop.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path

from docker.types import Mount

logger = logging.getLogger(__name__)

DEFAULT_X11_FALLBACK_DISPLAY = "host.docker.internal:0.0"
WSLG_ROOT = Path("/mnt/wslg")
WSLG_X11_SOCKET = WSLG_ROOT / ".X11-unix"
WSLG_LIB_DIR = Path("/usr/lib/wsl/lib")
WSLG_DXG_DEVICE = Path("/dev/dxg")
X11_UNIX_SOCKET = "/tmp/.X11-unix"  # nosec B108 - standard POSIX X11 socket dir
LINUX_X11_SOCKET = Path(X11_UNIX_SOCKET)
LINUX_DRI_DEVICE = Path("/dev/dri")


@dataclass(frozen=True)
class GuiSpec:
    """Resolved GUI forwarding configuration for a dev container."""

    backend: str
    mounts: list[Mount] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    devices: list[str] = field(default_factory=list)
    warning: str | None = None


def _x11_tcp_port_open(host: str = "127.0.0.1", port: int = 6000, timeout: float = 0.2) -> bool:
    """Return True if a local X11 server (e.g. VcXsrv, X410, XQuartz) is listening."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _windows_build_number() -> int:
    """Return the Windows OS build number, or 0 on non-Windows platforms."""
    get_ver = getattr(sys, "getwindowsversion", None)
    if get_ver is None:
        return 0
    try:
        return int(get_ver().build)
    except (AttributeError, ValueError, TypeError):
        return 0


def _wslg_linux_spec() -> GuiSpec:
    """Build GUI spec when running inside WSL2 with WSLg mounted at ``/mnt/wslg``."""
    mounts: list[Mount] = [
        Mount(target=X11_UNIX_SOCKET, source=str(WSLG_X11_SOCKET), type="bind"),
        Mount(target="/mnt/wslg", source=str(WSLG_ROOT), type="bind"),
    ]
    env: dict[str, str] = {
        "DISPLAY": os.environ.get("DISPLAY") or ":0",
        "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY") or "wayland-0",
        "XDG_RUNTIME_DIR": "/mnt/wslg/runtime-dir",
        "PULSE_SERVER": "/mnt/wslg/PulseServer",
    }
    devices: list[str] = []
    if WSLG_DXG_DEVICE.exists():
        devices.append(f"{WSLG_DXG_DEVICE}:{WSLG_DXG_DEVICE}")
    if WSLG_LIB_DIR.is_dir():
        mounts.append(
            Mount(
                target=str(WSLG_LIB_DIR),
                source=str(WSLG_LIB_DIR),
                type="bind",
                read_only=True,
            )
        )
        env["LD_LIBRARY_PATH"] = str(WSLG_LIB_DIR)
        env["GALLIUM_DRIVER"] = "d3d12"

    return GuiSpec(backend="wslg", mounts=mounts, environment=env, devices=devices)


def _wslg_windows_spec() -> GuiSpec:
    """Build GUI spec for native Windows 11 talking to Docker Desktop (WSL2 backend).

    Docker Desktop's Linux VM exposes Windows 11's WSLg sockets at ``/mnt/wslg``.
    If a Windows X11 server (VcXsrv/X410) is already listening on TCP 6000,
    prefer that direct X11 connection instead.
    """
    if _x11_tcp_port_open():
        return GuiSpec(
            backend="x11-tcp",
            environment={"DISPLAY": DEFAULT_X11_FALLBACK_DISPLAY},
        )

    build = _windows_build_number()
    if build >= 22000:
        return GuiSpec(
            backend="wslg",
            mounts=[
                Mount(target=X11_UNIX_SOCKET, source="/mnt/wslg/.X11-unix", type="bind"),
                Mount(target="/mnt/wslg", source="/mnt/wslg", type="bind"),
            ],
            environment={
                "DISPLAY": ":0",
                "WAYLAND_DISPLAY": "wayland-0",
                "XDG_RUNTIME_DIR": "/mnt/wslg/runtime-dir",
                "PULSE_SERVER": "/mnt/wslg/PulseServer",
            },
        )

    return GuiSpec(
        backend="x11-tcp",
        environment={"DISPLAY": DEFAULT_X11_FALLBACK_DISPLAY},
        warning=(
            "WSLg requires Windows 11; falling back to X11 at "
            f"DISPLAY={DEFAULT_X11_FALLBACK_DISPLAY} "
            "(start VcXsrv or X410 on Windows to display container windows)."
        ),
    )


def _linux_native_spec() -> GuiSpec:
    """Build GUI spec for a native Linux desktop (X11 and/or Wayland)."""
    display = os.environ.get("DISPLAY", "").strip()
    wayland = os.environ.get("WAYLAND_DISPLAY", "").strip()
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", "").strip()

    if not display and not wayland:
        return GuiSpec(
            backend="x11-tcp",
            environment={"DISPLAY": DEFAULT_X11_FALLBACK_DISPLAY},
            warning=(
                "No host DISPLAY or WAYLAND_DISPLAY detected; falling back to "
                f"DISPLAY={DEFAULT_X11_FALLBACK_DISPLAY}."
            ),
        )

    mounts: list[Mount] = []
    env: dict[str, str] = {}
    devices: list[str] = []

    if display:
        env["DISPLAY"] = display
        if LINUX_X11_SOCKET.is_dir():
            mounts.append(Mount(target=X11_UNIX_SOCKET, source=str(LINUX_X11_SOCKET), type="bind"))

    if wayland and xdg_runtime:
        wayland_sock = Path(xdg_runtime) / wayland
        if wayland_sock.exists():
            container_runtime = "/run/user/0"
            mounts.append(
                Mount(
                    target=f"{container_runtime}/{wayland}",
                    source=str(wayland_sock),
                    type="bind",
                )
            )
            env["WAYLAND_DISPLAY"] = wayland
            env["XDG_RUNTIME_DIR"] = container_runtime

    if LINUX_DRI_DEVICE.exists():
        devices.append(f"{LINUX_DRI_DEVICE}:{LINUX_DRI_DEVICE}")

    backend = "wayland" if (wayland and not display) else "x11"
    return GuiSpec(backend=backend, mounts=mounts, environment=env, devices=devices)


def resolve_gui_spec(display_override: str = "") -> GuiSpec:
    """Resolve the GUI forwarding mounts, devices, and env vars for the current host.

    Priority:
    1. Explicit *display_override* (``--gui-display`` / ``container.gui_display``).
    2. WSLg on WSL2 (``/mnt/wslg/.X11-unix`` present) — includes ``/dev/dxg`` GPU bridge.
    3. Windows 11 WSLg (or local VcXsrv/X410 if TCP 6000 is open; TCP fallback on Win10).
    4. Native Linux X11/Wayland sockets (or TCP fallback when headless).
    5. macOS / other platforms: X11 TCP fallback (``host.docker.internal:0.0``).
    """
    override = display_override.strip()
    if override:
        return GuiSpec(
            backend="x11-tcp",
            environment={"DISPLAY": override},
        )

    if sys.platform == "win32":
        return _wslg_windows_spec()

    if sys.platform.startswith("linux"):
        if WSLG_ROOT.is_dir() and WSLG_X11_SOCKET.is_dir():
            return _wslg_linux_spec()
        return _linux_native_spec()

    return GuiSpec(
        backend="x11-tcp",
        environment={"DISPLAY": DEFAULT_X11_FALLBACK_DISPLAY},
        warning=(
            f"Native GUI socket forwarding is not available on {sys.platform}; "
            f"falling back to DISPLAY={DEFAULT_X11_FALLBACK_DISPLAY} "
            "(start XQuartz / an X11 server on the host)."
        ),
    )
