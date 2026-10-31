"""A VPN container whose HTTP proxy carries the host Chrome's traffic.

Some hosts have an address that sites refuse: a cloud dev box, anything in a
datacenter. Google sign-in is the usual casualty. ai-shell cannot change the
host's route (no root on a dev box, and the dev container must keep its
direct path to Anthropic), so it runs the VPN in a container of its own,
`gluetun <https://github.com/qdm12/gluetun>`_, and hands only the browser to
it: gluetun's HTTP proxy listens on loopback, and Chrome is started with
``--proxy-server`` pointing at it (``claude.chrome_proxy: vpn``).

Provider: NordVPN over WireGuard. The credential is a NordVPN access token
(``NORDVPN_TOKEN`` in ``~/.augint/.env``; Nord Account, NordVPN, Manual
setup, Access token). gluetun needs the account's WireGuard private key, so
the token is traded for it once through NordVPN's API and the key is cached
under ``~/.augint/vpn/``; the token can expire, the key does not.

The container is a host-level singleton (``augint-shell-vpn``), like the LLM
stack: one per machine, shared by every project and account. Rootless Podman
runs it: ``NET_ADMIN`` and ``/dev/net/tun`` are enough, no root.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ai_shell.exceptions import AiShellError

if TYPE_CHECKING:
    from ai_shell.config import AiShellConfig
    from ai_shell.container import ContainerManager

logger = logging.getLogger(__name__)

VPN_CONTAINER = "augint-shell-vpn"
VPN_IMAGE = "docker.io/qmcgaw/gluetun:latest"
#: ``chrome_proxy: vpn`` means "the proxy of ai-shell's own VPN container".
VPN_PROXY_SENTINEL = "vpn"
VPN_TOKEN_VAR = "NORDVPN_TOKEN"
VPN_KEY_VAR = "NORDVPN_WIREGUARD_PRIVATE_KEY"
NORDVPN_CREDENTIALS_URL = "https://api.nordvpn.com/v1/users/services/credentials"
#: Container label that records the settings it was created with, so a
#: changed country, key or firewall setting recreates it instead of
#: silently keeping the old one.
VPN_CONFIG_LABEL = "ai-shell.vpn.config"
VPN_CHECK_URL = "https://api.ipify.org"
VPN_READY_TIMEOUT_SECONDS = 120.0
VPN_POLL_INTERVAL_SECONDS = 2.0
VPN_LOG_TAIL_LINES = 15
_WIREGUARD_KEY_BYTES = 32


class VpnUnavailable(AiShellError):
    """The VPN container could not be started or never came up."""


# ---------------------------------------------------------------- credentials


def vpn_state_dir() -> Path:
    """Directory for the cached WireGuard key and the firewall marker."""
    return Path.home() / ".augint" / "vpn"


def key_cache_path() -> Path:
    """Where the WireGuard private key derived from the token is kept (mode 0600)."""
    return vpn_state_dir() / "nordvpn-wireguard.key"


def firewall_off_marker() -> Path:
    """Present when gluetun's firewall failed here once; the container then runs without it."""
    return vpn_state_dir() / "firewall-off"


def _valid_wireguard_key(key: str) -> bool:
    try:
        return len(base64.b64decode(key, validate=True)) == _WIREGUARD_KEY_BYTES
    except (ValueError, TypeError):
        return False


def fetch_wireguard_key(token: str) -> str:
    """Trade a NordVPN access token for the account's WireGuard private key."""
    auth = base64.b64encode(f"token:{token.strip()}".encode()).decode("ascii")
    request = urllib.request.Request(  # noqa: S310 - fixed https URL
        NORDVPN_CREDENTIALS_URL,
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise VpnUnavailable(
                f"NordVPN refused the access token ({exc.code}). Tokens expire on the "
                f"schedule chosen when they were made: make a new one (Nord Account, NordVPN, "
                f"Manual setup, Access token) and put it in ~/.augint/.env as {VPN_TOKEN_VAR}=..."
            ) from exc
        raise VpnUnavailable(f"NordVPN API answered {exc.code} for the credentials call.") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise VpnUnavailable(f"Could not reach the NordVPN API: {exc}") from exc
    key = payload.get("nordlynx_private_key") if isinstance(payload, dict) else None
    if not isinstance(key, str) or not _valid_wireguard_key(key):
        raise VpnUnavailable(
            "NordVPN's credentials call returned no usable WireGuard key "
            "(nordlynx_private_key). Is the token a NordVPN access token, not a password?"
        )
    return key


def resolve_wireguard_key(
    env: Mapping[str, str | None],
    *,
    fetch: Callable[[str], str] = fetch_wireguard_key,
    prompt_token: Callable[[], str] | None = None,
) -> str:
    """Return the WireGuard private key for gluetun.

    Order: ``NORDVPN_WIREGUARD_PRIVATE_KEY`` in *env*, the cached key from an
    earlier token exchange, then ``NORDVPN_TOKEN`` in *env* (traded for the
    key and cached), then *prompt_token* when given. A missing credential is
    an error that names the exact line to add.
    """
    direct = (env.get(VPN_KEY_VAR) or "").strip()
    if direct:
        if not _valid_wireguard_key(direct):
            raise VpnUnavailable(f"{VPN_KEY_VAR} is not a WireGuard private key (44 characters).")
        return direct
    cache = key_cache_path()
    if cache.is_file():
        cached = cache.read_text(encoding="utf-8").strip()
        if _valid_wireguard_key(cached):
            return cached
        logger.warning("Ignoring an unreadable cached key at %s", cache)
    token = (env.get(VPN_TOKEN_VAR) or "").strip()
    if not token and prompt_token is not None:
        token = prompt_token().strip()
    if not token:
        raise VpnUnavailable(
            "No NordVPN credential. Add one line to ~/.augint/.env:\n"
            f"  {VPN_TOKEN_VAR}=<access token from Nord Account, NordVPN, Manual setup>\n"
            f"(or {VPN_KEY_VAR}=<WireGuard private key>). The token is exchanged once for the "
            "WireGuard key, which is cached under ~/.augint/vpn/."
        )
    key = fetch(token)
    _write_private(cache, key + "\n")
    logger.info("Cached the NordVPN WireGuard key at %s", cache)
    return key


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - Windows
        pass


# ------------------------------------------------------------------ container


def config_digest(key: str, country: str, firewall: bool, proxy_port: int) -> str:
    """Short digest of the settings a container was created with (no secret in it)."""
    material = f"{key}\n{country}\n{int(firewall)}\n{proxy_port}\n{VPN_IMAGE}".encode()
    return hashlib.sha256(material).hexdigest()[:16]


def run_kwargs(
    *, key: str, country: str, firewall: bool, proxy_port: int, digest: str
) -> dict[str, Any]:
    """``containers.run`` arguments for the gluetun container."""
    environment = {
        "VPN_SERVICE_PROVIDER": "nordvpn",
        "VPN_TYPE": "wireguard",
        "WIREGUARD_PRIVATE_KEY": key,
        "HTTPPROXY": "on",
        "HTTPPROXY_STEALTH": "on",
        "HTTPPROXY_LISTENING_ADDRESS": ":8888",
        "FIREWALL": "on" if firewall else "off",
        # Not a general-purpose VPN host: nothing else joins its network.
        "DOT": "on",
        "UPDATER_PERIOD": "24h",
    }
    if country:
        environment["SERVER_COUNTRIES"] = country
    return {
        "image": VPN_IMAGE,
        "name": VPN_CONTAINER,
        "detach": True,
        "cap_add": ["NET_ADMIN"],
        "devices": ["/dev/net/tun:/dev/net/tun:rwm"],
        "ports": {"8888/tcp": ("127.0.0.1", proxy_port)},
        "environment": environment,
        "labels": {VPN_CONFIG_LABEL: digest},
        "restart_policy": {"Name": "unless-stopped"},
    }


def proxy_url(proxy_port: int) -> str:
    """The proxy Chrome is pointed at."""
    return f"http://127.0.0.1:{proxy_port}"


def exit_address(proxy: str, timeout: float = 6.0) -> str | None:
    """The public address seen through *proxy*, or ``None`` when it does not answer."""
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    )
    try:
        with opener.open(VPN_CHECK_URL, timeout=timeout) as response:  # noqa: S310
            address = response.read(64).decode("ascii", "replace").strip()
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return address or None


def _tail(text: str, lines: int = VPN_LOG_TAIL_LINES) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def _looks_like_firewall_failure(log: str) -> bool:
    lowered = log.lower()
    return "firewall" in lowered and ("iptables" in lowered or "nftables" in lowered)


def wait_for_proxy(
    proxy: str,
    *,
    status: Callable[[], str | None],
    logs: Callable[[], str],
    timeout: float = VPN_READY_TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Poll until *proxy* carries traffic; return the exit address.

    Raises :class:`VpnUnavailable` with the container's last log lines when
    the container stops or the timeout passes.
    """
    deadline = time.monotonic() + timeout
    while True:
        address = exit_address(proxy)
        if address:
            return address
        state = status()
        if state not in ("running", "created", "restarting", "starting"):
            raise VpnUnavailable(
                f"The VPN container {VPN_CONTAINER} is {state or 'gone'}. Its last log lines:\n"
                f"{_tail(logs())}"
            )
        if time.monotonic() >= deadline:
            raise VpnUnavailable(
                f"The VPN container is running but its proxy at {proxy} did not carry traffic "
                f"within {int(timeout)} seconds. Its last log lines:\n{_tail(logs())}"
            )
        sleep(VPN_POLL_INTERVAL_SECONDS)


def _container_logs(container: Any) -> str:
    try:
        raw = container.logs(tail=200)
    except Exception as exc:  # pragma: no cover - defensive
        return f"(no logs: {exc})"
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return str(raw)


def _container_status(manager: ContainerManager) -> str | None:
    try:
        return manager.container_status(VPN_CONTAINER)
    except Exception:  # pragma: no cover - defensive
        return None


def ensure_vpn(
    manager: ContainerManager,
    *,
    key: str,
    country: str = "",
    firewall: bool = True,
    proxy_port: int = 8888,
    echo: Callable[[str], None] | None = None,
) -> str:
    """Make sure the VPN container runs with these settings and its proxy works.

    Returns the proxy URL. A container created with other settings is
    replaced. When gluetun cannot set up its firewall (rootless Podman on some
    hosts), the container is recreated once with the firewall off and a
    marker is written so later launches start that way at once.
    """
    echo = echo or (lambda _line: None)
    if firewall and firewall_off_marker().is_file():
        firewall = False
    proxy = proxy_url(proxy_port)
    digest = config_digest(key, country, firewall, proxy_port)

    container = manager._get_container(VPN_CONTAINER)
    if container is not None:
        labels = getattr(container, "labels", None)
        current = labels.get(VPN_CONFIG_LABEL) if isinstance(labels, dict) else None
        if current != digest:
            echo("VPN container settings changed; recreating it.")
            manager.remove_container(VPN_CONTAINER)
            container = None
        elif container.status != "running":
            echo("Starting the VPN container.")
            container.start()
    if container is None:
        echo(f"Creating the VPN container ({VPN_IMAGE}).")
        manager._pull_image_if_needed(VPN_IMAGE)
        manager.client.containers.run(
            **run_kwargs(
                key=key, country=country, firewall=firewall, proxy_port=proxy_port, digest=digest
            )
        )

    def logs() -> str:
        current = manager._get_container(VPN_CONTAINER)
        return _container_logs(current) if current is not None else "(container gone)"

    try:
        address = wait_for_proxy(proxy, status=lambda: _container_status(manager), logs=logs)
    except VpnUnavailable as exc:
        if not firewall or not _looks_like_firewall_failure(str(exc)):
            raise
        echo(
            "gluetun could not set up its firewall in this container runtime; "
            "running it without one (the proxy still goes through the tunnel)."
        )
        _write_private(firewall_off_marker(), "gluetun firewall failed here once\n")
        manager.remove_container(VPN_CONTAINER)
        return ensure_vpn(
            manager, key=key, country=country, firewall=False, proxy_port=proxy_port, echo=echo
        )
    echo(f"VPN up: traffic through the proxy leaves from {address}.")
    return proxy


def ensure_vpn_for_config(
    manager: ContainerManager,
    config: AiShellConfig,
    *,
    env_file: Path | None = None,
    prompt_token: Callable[[], str] | None = None,
    echo: Callable[[str], None] | None = None,
) -> str:
    """Resolve the credential from the layered ``.env`` and start the VPN."""
    from ai_shell.defaults import _load_layered_dotenv

    env: dict[str, str | None] = dict(os.environ)
    env.update(_load_layered_dotenv(config.project_dir, env_file))
    key = resolve_wireguard_key(env, prompt_token=prompt_token)
    return ensure_vpn(
        manager,
        key=key,
        country=config.vpn_country,
        firewall=config.vpn_firewall,
        proxy_port=config.vpn_proxy_port,
        echo=echo,
    )


def vpn_status(manager: ContainerManager, proxy_port: int = 8888) -> dict[str, str | None]:
    """Container state and, when it runs, the exit address through the proxy."""
    state = _container_status(manager)
    address = exit_address(proxy_url(proxy_port)) if state == "running" else None
    return {"status": state, "exit_address": address, "proxy": proxy_url(proxy_port)}


def remove_vpn(manager: ContainerManager) -> bool:
    """Stop and remove the VPN container and forget the firewall marker. True if one existed."""
    marker = firewall_off_marker()
    if marker.is_file():
        marker.unlink()
    if manager._get_container(VPN_CONTAINER) is None:
        return False
    manager.remove_container(VPN_CONTAINER)
    return True
