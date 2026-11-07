"""Tests for the host-side DevTools relay (Linux hosts)."""

import asyncio
import socket
from unittest.mock import MagicMock, patch

import pytest

from ai_shell import cdp_relay


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class TestAllowList:
    def test_local_addresses_hold_loopback_and_bind(self):
        addresses = cdp_relay.local_addresses("10.67.0.102")
        assert {"127.0.0.1", "::1", "10.67.0.102"} <= addresses

    def test_peer_allowed_unwraps_mapped_ipv6(self):
        allowed = {"127.0.0.1", "10.67.0.102"}
        assert cdp_relay.peer_allowed("10.67.0.102", allowed)
        assert cdp_relay.peer_allowed("::ffff:10.67.0.102", allowed)
        assert not cdp_relay.peer_allowed("10.67.0.55", allowed)
        assert not cdp_relay.peer_allowed("", allowed)

    def test_port_open_false_on_closed_port(self):
        assert cdp_relay.port_open(_free_port()) is False


class TestHandle:
    def test_foreign_peer_is_closed_without_upstream(self):
        writer = MagicMock()
        writer.get_extra_info.return_value = ("203.0.113.9", 4321)
        with patch("ai_shell.cdp_relay.asyncio.open_connection") as mock_open:
            asyncio.run(
                cdp_relay._handle(MagicMock(), writer, target_port=1, allowed={"127.0.0.1"})
            )
        mock_open.assert_not_called()
        writer.close.assert_called_once()


class TestServe:
    def test_relays_bytes_to_the_target(self):
        async def scenario() -> bytes:
            async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                data = await reader.read(1024)
                writer.write(b"echo:" + data)
                await writer.drain()
                writer.close()

            target_port = _free_port()
            relay_port = _free_port()
            target = await asyncio.start_server(echo, "127.0.0.1", target_port)
            relay = asyncio.create_task(
                cdp_relay.serve("127.0.0.1", relay_port, target_port=target_port)
            )
            try:
                for _ in range(50):
                    if cdp_relay.port_open(relay_port):
                        break
                    await asyncio.sleep(0.05)
                reader, writer = await asyncio.open_connection("127.0.0.1", relay_port)
                writer.write(b"GET /json/version")
                await writer.drain()
                answer = await asyncio.wait_for(reader.read(1024), timeout=5)
                writer.close()
                return answer
            finally:
                relay.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await relay
                target.close()
                await target.wait_closed()

        assert asyncio.run(scenario()) == b"echo:GET /json/version"

    def test_watchdog_exits_when_target_never_opens(self):
        async def scenario() -> None:
            stop = asyncio.Event()
            with (
                patch("ai_shell.cdp_relay.STARTUP_GRACE_SECONDS", 0.0),
                patch("ai_shell.cdp_relay.WATCHDOG_INTERVAL_SECONDS", 0.01),
            ):
                await asyncio.wait_for(cdp_relay._watchdog(_free_port(), stop), timeout=5)
            assert stop.is_set()

        asyncio.run(scenario())


class TestMain:
    def test_bad_bind_address_is_exit_1(self):
        assert cdp_relay.main(["256.1.1.1", "1"]) == 1
