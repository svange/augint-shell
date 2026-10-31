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

An account that owns a NordVPN dedicated IP gets it without being asked: the
same token names the dedicated-IP server (``/v1/users/services``), and
gluetun is pinned to that server (``SERVER_HOSTNAMES``). A shared NordVPN
exit is a datacenter address like any other and Google scores it the same
way; the dedicated IP is the one the account's owner already uses. The
hostname is cached next to the key; ``NORDVPN_SERVER`` in ``.env`` overrides
it (a hostname, or ``any`` for a shared server).

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
import re
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
#: Pins gluetun to one NordVPN server (``us2943`` or ``us2943.nordvpn.com``);
#: ``any`` forces a shared server even when the account has a dedicated IP.
VPN_SERVER_VAR = "NORDVPN_SERVER"
VPN_SERVER_ANY = "any"
NORDVPN_CREDENTIALS_URL = "https://api.nordvpn.com/v1/users/services/credentials"
NORDVPN_SERVICES_URL = "https://api.nordvpn.com/v1/users/services"
NORDVPN_SERVERS_URL = "https://api.nordvpn.com/v1/servers"
NORDVPN_SERVER_SUFFIX = ".nordvpn.com"
_SERVER_HOSTNAME = re.compile(r"^[a-z0-9][a-z0-9.-]*[a-z0-9]$")
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


def server_cache_path() -> Path:
    """Where the account's dedicated-IP server hostname is kept (empty file: none)."""
    return vpn_state_dir() / "nordvpn-server"


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
        # Fixed https URL to NordVPN's API, never a user-supplied scheme.
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 # nosec B310
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


def _nordvpn_get(url: str, token: str | None = None) -> Any:
    """GET a NordVPN API URL as JSON; *token* adds the ``token:<token>`` basic auth."""
    headers = {"Accept": "application/json"}
    if token:
        auth = base64.b64encode(f"token:{token.strip()}".encode()).decode("ascii")
        headers["Authorization"] = f"Basic {auth}"
    request = urllib.request.Request(url, headers=headers)  # noqa: S310 - fixed https URLs
    try:
        # Fixed https URLs under api.nordvpn.com, never a user-supplied scheme.
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 # nosec B310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise VpnUnavailable(f"NordVPN API answered {exc.code} for {url}.") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise VpnUnavailable(f"Could not reach the NordVPN API: {exc}") from exc


def fetch_dedicated_ip_server(token: str) -> str:
    """Hostname of the account's dedicated-IP server, or ``""`` when it owns none.

    ``/v1/users/services`` lists the account's services; the ``dedicated_ip``
    one carries the server ids under ``details.servers``. ``/v1/servers``
    filtered by that id gives the hostname gluetun filters on.
    """
    services = _nordvpn_get(NORDVPN_SERVICES_URL, token)
    server_ids: list[int] = []
    for item in services if isinstance(services, list) else []:
        if not isinstance(item, dict):
            continue
        service = item.get("service")
        identifier = service.get("identifier") if isinstance(service, dict) else None
        if identifier != "dedicated_ip":
            continue
        details = item.get("details")
        servers = details.get("servers") if isinstance(details, dict) else None
        for server in servers if isinstance(servers, list) else []:
            server_id = server.get("id") if isinstance(server, dict) else None
            if isinstance(server_id, int):
                server_ids.append(server_id)
    if not server_ids:
        return ""
    url = f"{NORDVPN_SERVERS_URL}?filters[servers.id]={server_ids[0]}&fields[servers.hostname]"
    servers = _nordvpn_get(url)
    first = servers[0] if isinstance(servers, list) and servers else None
    hostname = first.get("hostname") if isinstance(first, dict) else None
    if not isinstance(hostname, str) or not hostname:
        raise VpnUnavailable(
            f"NordVPN lists a dedicated IP on server id {server_ids[0]} but /v1/servers "
            "returned no hostname for it."
        )
    return normalize_server(hostname)


def normalize_server(value: str) -> str:
    """``us2943`` or ``US2943.nordvpn.com`` to ``us2943.nordvpn.com``; ``any`` or empty to ``""``."""
    server = value.strip().lower()
    if not server or server == VPN_SERVER_ANY:
        return ""
    if "." not in server:
        server += NORDVPN_SERVER_SUFFIX
    if not _SERVER_HOSTNAME.match(server):
        raise VpnUnavailable(
            f"{VPN_SERVER_VAR}={value!r} is not a NordVPN server name (us2943 or "
            f"us2943.nordvpn.com, or '{VPN_SERVER_ANY}')."
        )
    return server


def configured_server(env: Mapping[str, str | None]) -> str | None:
    """The pinned server without any API call: ``NORDVPN_SERVER``, else the cache, else None."""
    override = env.get(VPN_SERVER_VAR)
    if override is not None and override.strip():
        return normalize_server(override)
    cache = server_cache_path()
    if cache.is_file():
        return normalize_server(cache.read_text(encoding="utf-8"))
    return None


def resolve_server(
    env: Mapping[str, str | None],
    *,
    fetch: Callable[[str], str] = fetch_dedicated_ip_server,
) -> str:
    """The NordVPN server gluetun is pinned to, ``""`` for any server.

    Order: ``NORDVPN_SERVER`` in *env* (``any`` means a shared server), the
    cached answer from an earlier lookup, then the account's dedicated-IP
    server looked up with ``NORDVPN_TOKEN`` and cached (an empty cache file
    records "no dedicated IP"). Without a token nothing is pinned. A token
    NordVPN refuses leaves the server unpinned instead of blocking a start
    whose WireGuard key is already cached.
    """
    known = configured_server(env)
    if known is not None:
        return known
    token = (env.get(VPN_TOKEN_VAR) or "").strip()
    if not token:
        return ""
    try:
        server = fetch(token)
    except VpnUnavailable as exc:
        if " 401 " in str(exc) or " 403 " in str(exc):
            logger.warning("NordVPN did not accept the dedicated-IP lookup: %s", exc)
            return ""
        raise
    _write_private(server_cache_path(), server + "\n")
    logger.info("Cached the NordVPN server %r at %s", server, server_cache_path())
    return server


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


def config_digest(key: str, country: str, firewall: bool, proxy_port: int, server: str = "") -> str:
    """Short digest of the settings a container was created with (no secret in it)."""
    material = f"{key}\n{country}\n{int(firewall)}\n{proxy_port}\n{VPN_IMAGE}\n{server}".encode()
    return hashlib.sha256(material).hexdigest()[:16]


def run_kwargs(
    *, key: str, country: str, firewall: bool, proxy_port: int, digest: str, server: str = ""
) -> dict[str, Any]:
    """``containers.run`` arguments for the gluetun container.

    *server* pins gluetun to one hostname (the account's dedicated-IP server)
    and then replaces the country filter: gluetun ANDs its filters, and a
    country that does not match the pinned server would leave it no server.
    """
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
    if server:
        environment["SERVER_HOSTNAMES"] = server
    elif country:
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
    server: str = "",
    echo: Callable[[str], None] | None = None,
) -> str:
    """Make sure the VPN container runs with these settings and its proxy works.

    Returns the proxy URL. A container created with other settings is
    replaced. *server* pins gluetun to one NordVPN hostname (see
    :func:`resolve_server`). When gluetun cannot set up its firewall (rootless Podman on some
    hosts), the container is recreated once with the firewall off and a
    marker is written so later launches start that way at once.
    """
    echo = echo or (lambda _line: None)
    if firewall and firewall_off_marker().is_file():
        firewall = False
    proxy = proxy_url(proxy_port)
    digest = config_digest(key, country, firewall, proxy_port, server)

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
                key=key,
                country=country,
                firewall=firewall,
                proxy_port=proxy_port,
                digest=digest,
                server=server,
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
            manager,
            key=key,
            country=country,
            firewall=False,
            proxy_port=proxy_port,
            server=server,
            echo=echo,
        )
    where = f" (server {server})" if server else ""
    echo(f"VPN up: traffic through the proxy leaves from {address}{where}.")
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

    def remembered_prompt() -> str:
        # A token typed at the prompt also serves the dedicated-IP lookup.
        token = prompt_token() if prompt_token is not None else ""
        env[VPN_TOKEN_VAR] = token
        return token

    key = resolve_wireguard_key(
        env, prompt_token=remembered_prompt if prompt_token is not None else None
    )
    server = resolve_server(env)
    if server:
        (echo or (lambda _line: None))(f"Using the account's dedicated-IP server {server}.")
    return ensure_vpn(
        manager,
        key=key,
        country=config.vpn_country,
        firewall=config.vpn_firewall,
        proxy_port=config.vpn_proxy_port,
        server=server,
        echo=echo,
    )


def vpn_status(manager: ContainerManager, proxy_port: int = 8888) -> dict[str, str | None]:
    """Container state, the pinned server (no API call) and, when it runs, the exit address."""
    state = _container_status(manager)
    address = exit_address(proxy_url(proxy_port)) if state == "running" else None
    try:
        server = configured_server(os.environ) or None
    except VpnUnavailable:
        server = None
    return {
        "status": state,
        "exit_address": address,
        "proxy": proxy_url(proxy_port),
        "server": server,
    }


def remove_vpn(manager: ContainerManager) -> bool:
    """Stop and remove the VPN container and forget the firewall marker. True if one existed."""
    for path in (firewall_off_marker(), server_cache_path()):
        if path.is_file():
            path.unlink()
    if manager._get_container(VPN_CONTAINER) is None:
        return False
    manager.remove_container(VPN_CONTAINER)
    return True
