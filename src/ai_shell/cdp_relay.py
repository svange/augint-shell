"""A host-side relay from the address containers reach to Chrome's loopback port.

A windowed Chrome binds its DevTools port to ``127.0.0.1`` only: it ignores
``--remote-debugging-address`` (that flag works in the old headless shell
alone). On Docker Desktop that is fine, because ``host.docker.internal``
lands on the host's loopback. On a Linux host (Docker or Podman) the
container reaches the host at a real address, where nothing listens, so the
bridge never connected there.

This relay listens on that address, on the same port number, and forwards
each connection to ``127.0.0.1:<port>``. It accepts connections only from
the host's own addresses: a rootless Podman or Docker container's traffic
arrives from one of them, while another machine on the network does not, so
the DevTools port (which has no authentication) stays private to this host.

It exits by itself once Chrome's loopback port has been gone for a while,
so it never outlives the browser for long. ``python -m ai_shell.cdp_relay
<bind-address> <port>`` runs it; ai-shell starts it detached.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import socket
import sys
import time

logger = logging.getLogger(__name__)

LOOPBACK = "127.0.0.1"
#: How often the relay checks that Chrome still answers on loopback.
WATCHDOG_INTERVAL_SECONDS = 5.0
#: How long Chrome's port may stay closed before the relay exits.
WATCHDOG_GRACE_SECONDS = 30.0
#: How long after start the relay waits for Chrome's port to open at all.
STARTUP_GRACE_SECONDS = 90.0
BUFFER_BYTES = 65536


def local_addresses(bind_address: str = "") -> set[str]:
    """Every address that is this host: loopback, the bind address, all interfaces."""
    addresses = {LOOPBACK, "::1"}
    if bind_address:
        addresses.add(bind_address)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            addresses.add(str(info[4][0]))
    except OSError:
        pass
    return addresses


def peer_allowed(peer: str, allowed: set[str]) -> bool:
    """True when *peer* (an IP text, IPv4-mapped IPv6 unwrapped) is one of *allowed*."""
    if peer.startswith("::ffff:"):
        peer = peer[len("::ffff:") :]
    return peer in allowed


def port_open(port: int, host: str = LOOPBACK, timeout: float = 1.0) -> bool:
    """True when something accepts a TCP connection on *host*:*port*."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


async def _pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(BUFFER_BYTES)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError, OSError):
        pass
    finally:
        with contextlib.suppress(Exception):
            writer.close()


async def _handle(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    target_port: int,
    allowed: set[str],
) -> None:
    peer = writer.get_extra_info("peername")
    peer_host = str(peer[0]) if peer else ""
    if not peer_allowed(peer_host, allowed):
        logger.warning("Refused a DevTools connection from %s", peer_host or "unknown")
        writer.close()
        return
    try:
        upstream_reader, upstream_writer = await asyncio.open_connection(LOOPBACK, target_port)
    except OSError as exc:
        logger.info("Chrome's loopback port %d refused: %s", target_port, exc)
        writer.close()
        return
    await asyncio.gather(
        _pump(reader, upstream_writer),
        _pump(upstream_reader, writer),
    )


async def _watchdog(target_port: int, stop: asyncio.Event) -> None:
    started = time.monotonic()
    seen = False
    last_seen = started
    while not stop.is_set():
        if port_open(target_port):
            seen = True
            last_seen = time.monotonic()
        else:
            now = time.monotonic()
            grace = WATCHDOG_GRACE_SECONDS if seen else STARTUP_GRACE_SECONDS
            if now - last_seen > grace:
                logger.info("Chrome's loopback port %d is gone; relay exiting", target_port)
                stop.set()
                return
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=WATCHDOG_INTERVAL_SECONDS)


async def serve(bind_address: str, port: int, target_port: int | None = None) -> None:
    """Run the relay until Chrome's port is gone (or the task is cancelled)."""
    target = target_port or port
    allowed = local_addresses(bind_address)
    stop = asyncio.Event()

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _handle(reader, writer, target_port=target, allowed=allowed)

    server = await asyncio.start_server(handler, bind_address, port)
    logger.info("Relaying %s:%d -> %s:%d", bind_address, port, LOOPBACK, target)
    watchdog = asyncio.create_task(_watchdog(target, stop))
    try:
        await stop.wait()
    finally:
        watchdog.cancel()
        server.close()
        await server.wait_closed()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bind_address", help="address the containers reach the host at")
    parser.add_argument("port", type=int, help="port to listen on and to forward to")
    parser.add_argument(
        "--target-port", type=int, default=None, help="Chrome's loopback port (default: PORT)"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(serve(args.bind_address, args.port, args.target_port))
    except OSError as exc:
        logger.error("Relay could not listen on %s:%d: %s", args.bind_address, args.port, exc)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit(main())
