"""Tests for the VPN container (gluetun) behind ``chrome_proxy: vpn``."""

import base64
import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from ai_shell.vpn import (
    VPN_CONFIG_LABEL,
    VPN_CONTAINER,
    VPN_IMAGE,
    VpnUnavailable,
    config_digest,
    configured_server,
    ensure_vpn,
    ensure_vpn_for_config,
    fetch_dedicated_ip_server,
    fetch_wireguard_key,
    firewall_off_marker,
    key_cache_path,
    normalize_server,
    remove_vpn,
    resolve_server,
    resolve_wireguard_key,
    run_kwargs,
    server_cache_path,
    vpn_status,
    wait_for_proxy,
)

KEY = base64.b64encode(bytes(range(32))).decode()
TOKEN = "0123456789abcdef" * 4


class TestCredentials:
    def test_direct_key_wins(self, isolate_home):
        assert resolve_wireguard_key({"NORDVPN_WIREGUARD_PRIVATE_KEY": KEY}) == KEY

    def test_direct_key_must_be_a_key(self, isolate_home):
        with pytest.raises(VpnUnavailable, match="not a WireGuard private key"):
            resolve_wireguard_key({"NORDVPN_WIREGUARD_PRIVATE_KEY": "nope"})

    def test_token_is_exchanged_once_and_cached(self, isolate_home):
        fetch = MagicMock(return_value=KEY)

        assert resolve_wireguard_key({"NORDVPN_TOKEN": TOKEN}, fetch=fetch) == KEY
        fetch.assert_called_once_with(TOKEN)
        cache = key_cache_path()
        assert cache.read_text().strip() == KEY
        assert (cache.stat().st_mode & 0o777) == 0o600

        # Second call: cache, no API.
        assert resolve_wireguard_key({"NORDVPN_TOKEN": TOKEN}, fetch=fetch) == KEY
        fetch.assert_called_once()

    def test_missing_credential_names_the_env_line(self, isolate_home):
        with pytest.raises(VpnUnavailable, match=r"NORDVPN_TOKEN=<access token"):
            resolve_wireguard_key({}, fetch=MagicMock())

    def test_prompt_is_the_last_resort(self, isolate_home):
        fetch = MagicMock(return_value=KEY)
        assert resolve_wireguard_key({}, fetch=fetch, prompt_token=lambda: TOKEN) == KEY
        fetch.assert_called_once_with(TOKEN)

    def test_empty_prompt_is_an_error(self, isolate_home):
        with pytest.raises(VpnUnavailable, match="No NordVPN credential"):
            resolve_wireguard_key({}, fetch=MagicMock(), prompt_token=lambda: "  ")


class TestFetchKey:
    def _response(self, payload):
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode()
        response.__enter__ = lambda s: s
        response.__exit__ = MagicMock(return_value=False)
        return response

    @patch("ai_shell.vpn.urllib.request.urlopen")
    def test_sends_basic_auth_and_returns_key(self, mock_open):
        mock_open.return_value = self._response({"nordlynx_private_key": KEY, "id": 1})

        assert fetch_wireguard_key(TOKEN) == KEY
        request = mock_open.call_args[0][0]
        expected = base64.b64encode(f"token:{TOKEN}".encode()).decode()
        assert request.get_header("Authorization") == f"Basic {expected}"
        assert request.full_url == "https://api.nordvpn.com/v1/users/services/credentials"

    @patch("ai_shell.vpn.urllib.request.urlopen")
    def test_refused_token_says_so(self, mock_open):
        mock_open.side_effect = urllib.error.HTTPError(
            "https://api.nordvpn.com", 401, "Unauthorized", {}, io.BytesIO(b"")
        )
        with pytest.raises(VpnUnavailable, match="refused the access token"):
            fetch_wireguard_key(TOKEN)

    @patch("ai_shell.vpn.urllib.request.urlopen")
    def test_payload_without_key_is_an_error(self, mock_open):
        mock_open.return_value = self._response({"username": "x"})
        with pytest.raises(VpnUnavailable, match="no usable WireGuard key"):
            fetch_wireguard_key(TOKEN)


def _json_response(payload):
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode()
    response.__enter__ = lambda s: s
    response.__exit__ = MagicMock(return_value=False)
    return response


SERVICES = [
    {"id": 1, "service": {"id": 1, "identifier": "vpn"}, "details": {}},
    {
        "id": 2,
        "service": {"id": 7, "identifier": "dedicated_ip"},
        "details": {"servers": [{"id": 947235}]},
    },
]
SERVER_ROWS = [{"hostname": "us2943.nordvpn.com", "id": 947235}]


class TestDedicatedIpServer:
    @patch("ai_shell.vpn.urllib.request.urlopen")
    def test_looks_up_the_account_server(self, mock_open):
        mock_open.side_effect = [_json_response(SERVICES), _json_response(SERVER_ROWS)]

        assert fetch_dedicated_ip_server(TOKEN) == "us2943.nordvpn.com"

        services_request = mock_open.call_args_list[0][0][0]
        expected = base64.b64encode(f"token:{TOKEN}".encode()).decode()
        assert services_request.full_url == "https://api.nordvpn.com/v1/users/services"
        assert services_request.get_header("Authorization") == f"Basic {expected}"
        servers_request = mock_open.call_args_list[1][0][0]
        assert servers_request.full_url == (
            "https://api.nordvpn.com/v1/servers?filters[servers.id]=947235&fields[servers.hostname]"
        )
        assert servers_request.get_header("Authorization") is None

    @patch("ai_shell.vpn.urllib.request.urlopen")
    def test_account_without_dedicated_ip_is_empty(self, mock_open):
        mock_open.return_value = _json_response(SERVICES[:1])
        assert fetch_dedicated_ip_server(TOKEN) == ""
        mock_open.assert_called_once()

    @patch("ai_shell.vpn.urllib.request.urlopen")
    def test_server_without_hostname_is_an_error(self, mock_open):
        mock_open.side_effect = [_json_response(SERVICES), _json_response([])]
        with pytest.raises(VpnUnavailable, match="no hostname"):
            fetch_dedicated_ip_server(TOKEN)

    @patch("ai_shell.vpn.urllib.request.urlopen")
    def test_api_error_names_the_status(self, mock_open):
        mock_open.side_effect = urllib.error.HTTPError(
            "https://api.nordvpn.com", 500, "Server Error", {}, io.BytesIO(b"")
        )
        with pytest.raises(VpnUnavailable, match="answered 500"):
            fetch_dedicated_ip_server(TOKEN)

    def test_normalize(self):
        assert normalize_server("us2943") == "us2943.nordvpn.com"
        assert normalize_server(" US2943.nordvpn.com\n") == "us2943.nordvpn.com"
        assert normalize_server("") == ""
        assert normalize_server("any") == ""
        with pytest.raises(VpnUnavailable, match="not a NordVPN server name"):
            normalize_server("us 2943")


class TestResolveServer:
    def test_override_wins_without_api(self, isolate_home):
        fetch = MagicMock()
        env = {"NORDVPN_SERVER": "us2943", "NORDVPN_TOKEN": TOKEN}
        assert resolve_server(env, fetch=fetch) == "us2943.nordvpn.com"
        assert configured_server(env) == "us2943.nordvpn.com"
        fetch.assert_not_called()

    def test_any_forces_a_shared_server(self, isolate_home):
        server_cache_path().parent.mkdir(parents=True)
        server_cache_path().write_text("us2943.nordvpn.com\n")
        assert resolve_server({"NORDVPN_SERVER": "any"}, fetch=MagicMock()) == ""

    def test_token_lookup_is_cached(self, isolate_home):
        fetch = MagicMock(return_value="us2943.nordvpn.com")
        env = {"NORDVPN_TOKEN": TOKEN}

        assert resolve_server(env, fetch=fetch) == "us2943.nordvpn.com"
        fetch.assert_called_once_with(TOKEN)
        assert server_cache_path().read_text().strip() == "us2943.nordvpn.com"
        assert configured_server({}) == "us2943.nordvpn.com"

        assert resolve_server(env, fetch=fetch) == "us2943.nordvpn.com"
        fetch.assert_called_once()

    def test_no_dedicated_ip_is_remembered(self, isolate_home):
        fetch = MagicMock(return_value="")
        assert resolve_server({"NORDVPN_TOKEN": TOKEN}, fetch=fetch) == ""
        assert server_cache_path().is_file()
        assert configured_server({}) == ""
        assert resolve_server({"NORDVPN_TOKEN": TOKEN}, fetch=fetch) == ""
        fetch.assert_called_once()

    def test_without_token_nothing_is_pinned(self, isolate_home):
        fetch = MagicMock()
        assert resolve_server({}, fetch=fetch) == ""
        assert configured_server({}) is None
        fetch.assert_not_called()
        assert not server_cache_path().exists()

    def test_refused_token_does_not_block(self, isolate_home):
        fetch = MagicMock(side_effect=VpnUnavailable("NordVPN API answered 401 for x."))
        assert resolve_server({"NORDVPN_TOKEN": TOKEN}, fetch=fetch) == ""
        assert not server_cache_path().exists()

    def test_other_lookup_failures_propagate(self, isolate_home):
        fetch = MagicMock(side_effect=VpnUnavailable("Could not reach the NordVPN API: x"))
        with pytest.raises(VpnUnavailable, match="Could not reach"):
            resolve_server({"NORDVPN_TOKEN": TOKEN}, fetch=fetch)


class TestRunKwargs:
    def test_gluetun_settings(self):
        kwargs = run_kwargs(
            key=KEY, country="United States", firewall=True, proxy_port=8888, digest="d"
        )
        assert kwargs["image"] == VPN_IMAGE
        assert kwargs["name"] == VPN_CONTAINER
        assert kwargs["cap_add"] == ["NET_ADMIN"]
        assert kwargs["devices"] == ["/dev/net/tun:/dev/net/tun:rwm"]
        assert kwargs["ports"] == {"8888/tcp": ("127.0.0.1", 8888)}
        assert kwargs["labels"] == {VPN_CONFIG_LABEL: "d"}
        env = kwargs["environment"]
        assert env["VPN_SERVICE_PROVIDER"] == "nordvpn"
        assert env["VPN_TYPE"] == "wireguard"
        assert env["WIREGUARD_PRIVATE_KEY"] == KEY
        assert env["HTTPPROXY"] == "on"
        assert env["SERVER_COUNTRIES"] == "United States"
        assert env["FIREWALL"] == "on"

    def test_no_country_and_firewall_off(self):
        env = run_kwargs(key=KEY, country="", firewall=False, proxy_port=1, digest="d")[
            "environment"
        ]
        assert "SERVER_COUNTRIES" not in env
        assert "SERVER_HOSTNAMES" not in env
        assert env["FIREWALL"] == "off"

    def test_server_pins_the_hostname_and_replaces_the_country(self):
        env = run_kwargs(
            key=KEY,
            country="Canada",
            firewall=True,
            proxy_port=1,
            digest="d",
            server="us2943.nordvpn.com",
        )["environment"]
        assert env["SERVER_HOSTNAMES"] == "us2943.nordvpn.com"
        assert "SERVER_COUNTRIES" not in env

    def test_digest_changes_with_settings_and_hides_the_key(self):
        a = config_digest(KEY, "US", True, 8888)
        assert a != config_digest(KEY, "CA", True, 8888)
        assert a != config_digest(KEY, "US", False, 8888)
        assert a != config_digest("other", "US", True, 8888)
        assert a != config_digest(KEY, "US", True, 8888, "us2943.nordvpn.com")
        assert KEY not in a and len(a) == 16


class TestWaitForProxy:
    @patch("ai_shell.vpn.exit_address", return_value="203.0.113.9")
    def test_returns_exit_address(self, mock_exit):
        assert (
            wait_for_proxy(
                "http://127.0.0.1:8888",
                status=lambda: "running",
                logs=lambda: "",
                sleep=lambda s: None,
            )
            == "203.0.113.9"
        )

    @patch("ai_shell.vpn.exit_address", return_value=None)
    def test_stopped_container_raises_with_logs(self, mock_exit):
        with pytest.raises(VpnUnavailable, match="is exited") as info:
            wait_for_proxy(
                "http://127.0.0.1:8888",
                status=lambda: "exited",
                logs=lambda: "line1\nboom",
                sleep=lambda s: None,
            )
        assert "boom" in str(info.value)

    @patch("ai_shell.vpn.exit_address", return_value=None)
    @patch("ai_shell.vpn.time.monotonic", side_effect=[0.0, 0.0, 200.0])
    def test_timeout_raises(self, mock_clock, mock_exit):
        with pytest.raises(VpnUnavailable, match="did not carry traffic"):
            wait_for_proxy(
                "http://127.0.0.1:8888",
                status=lambda: "running",
                logs=lambda: "",
                timeout=100.0,
                sleep=lambda s: None,
            )


class TestEnsureVpn:
    def _manager(self, container=None, status=None):
        manager = MagicMock()
        manager._get_container.return_value = container
        manager.container_status.return_value = status
        return manager

    @patch("ai_shell.vpn.wait_for_proxy", return_value="203.0.113.9")
    def test_creates_when_missing(self, mock_wait, isolate_home):
        manager = self._manager()
        lines: list[str] = []

        proxy = ensure_vpn(manager, key=KEY, country="United States", echo=lines.append)

        assert proxy == "http://127.0.0.1:8888"
        manager._pull_image_if_needed.assert_called_once_with(VPN_IMAGE)
        kwargs = manager.client.containers.run.call_args[1]
        assert kwargs["name"] == VPN_CONTAINER
        assert kwargs["labels"][VPN_CONFIG_LABEL] == config_digest(KEY, "United States", True, 8888)
        assert any("203.0.113.9" in line for line in lines)

    @patch("ai_shell.vpn.wait_for_proxy", return_value="203.0.113.9")
    def test_reuses_running_container_with_same_settings(self, mock_wait, isolate_home):
        container = MagicMock(status="running")
        container.labels = {VPN_CONFIG_LABEL: config_digest(KEY, "", True, 8888)}
        manager = self._manager(container)

        ensure_vpn(manager, key=KEY)

        manager.client.containers.run.assert_not_called()
        manager.remove_container.assert_not_called()
        container.start.assert_not_called()

    @patch("ai_shell.vpn.wait_for_proxy", return_value="203.0.113.9")
    def test_starts_stopped_container(self, mock_wait, isolate_home):
        container = MagicMock(status="exited")
        container.labels = {VPN_CONFIG_LABEL: config_digest(KEY, "", True, 8888)}
        manager = self._manager(container)

        ensure_vpn(manager, key=KEY)

        container.start.assert_called_once()
        manager.client.containers.run.assert_not_called()

    @patch("ai_shell.vpn.wait_for_proxy", return_value="203.0.113.9")
    def test_recreates_when_settings_changed(self, mock_wait, isolate_home):
        container = MagicMock(status="running")
        container.labels = {VPN_CONFIG_LABEL: "stale"}
        manager = self._manager(container)

        ensure_vpn(manager, key=KEY, country="Canada")

        manager.remove_container.assert_called_once_with(VPN_CONTAINER)
        assert manager.client.containers.run.call_args[1]["environment"]["SERVER_COUNTRIES"] == (
            "Canada"
        )

    @patch("ai_shell.vpn.wait_for_proxy")
    def test_firewall_failure_falls_back_once_and_remembers(self, mock_wait, isolate_home):
        mock_wait.side_effect = [
            VpnUnavailable(
                "container is exited. logs:\nERROR firewall: iptables: Permission denied"
            ),
            "203.0.113.9",
        ]
        manager = self._manager()
        lines: list[str] = []

        ensure_vpn(manager, key=KEY, echo=lines.append)

        runs = manager.client.containers.run.call_args_list
        assert [c[1]["environment"]["FIREWALL"] for c in runs] == ["on", "off"]
        manager.remove_container.assert_called_once_with(VPN_CONTAINER)
        assert firewall_off_marker().is_file()
        assert any("without one" in line for line in lines)

        # Next time the marker starts it without the firewall at once.
        manager2 = self._manager()
        mock_wait.side_effect = None
        mock_wait.return_value = "203.0.113.9"
        ensure_vpn(manager2, key=KEY)
        assert manager2.client.containers.run.call_args[1]["environment"]["FIREWALL"] == "off"

    @patch("ai_shell.vpn.wait_for_proxy", side_effect=VpnUnavailable("exited. logs:\nbad key"))
    def test_other_failures_propagate(self, mock_wait, isolate_home):
        with pytest.raises(VpnUnavailable, match="bad key"):
            ensure_vpn(self._manager(), key=KEY)
        assert not firewall_off_marker().is_file()

    @patch("ai_shell.vpn.ensure_vpn", return_value="http://127.0.0.1:8890")
    def test_for_config_reads_layered_env_and_settings(self, mock_ensure, isolate_home, tmp_path):
        from ai_shell.config import AiShellConfig

        augint = isolate_home / ".augint"
        augint.mkdir()
        (augint / ".env").write_text(
            f"NORDVPN_WIREGUARD_PRIVATE_KEY={KEY}\nNORDVPN_SERVER=us2943\n"
        )
        config = AiShellConfig(project_name="demo", project_dir=tmp_path)
        config.vpn_country = "United States"
        config.vpn_firewall = False
        config.vpn_proxy_port = 8890
        manager = MagicMock()

        assert ensure_vpn_for_config(manager, config) == "http://127.0.0.1:8890"
        assert mock_ensure.call_args[1] == {
            "key": KEY,
            "country": "United States",
            "firewall": False,
            "proxy_port": 8890,
            "server": "us2943.nordvpn.com",
            "echo": None,
        }

    @patch("ai_shell.vpn.urllib.request.urlopen")
    @patch("ai_shell.vpn.ensure_vpn", return_value="http://127.0.0.1:8888")
    def test_for_config_prompted_token_serves_both_lookups(
        self, mock_ensure, mock_open, isolate_home, tmp_path
    ):
        from ai_shell.config import AiShellConfig

        mock_open.side_effect = [
            _json_response({"nordlynx_private_key": KEY}),
            _json_response(SERVICES),
            _json_response(SERVER_ROWS),
        ]
        config = AiShellConfig(project_name="demo", project_dir=tmp_path)
        lines: list[str] = []
        prompt = MagicMock(return_value=TOKEN)

        ensure_vpn_for_config(MagicMock(), config, prompt_token=prompt, echo=lines.append)

        prompt.assert_called_once()
        expected = base64.b64encode(f"token:{TOKEN}".encode()).decode()
        for call in mock_open.call_args_list[:2]:
            assert call[0][0].get_header("Authorization") == f"Basic {expected}"
        assert mock_ensure.call_args[1]["key"] == KEY
        assert mock_ensure.call_args[1]["server"] == "us2943.nordvpn.com"
        assert lines == ["Using the account's dedicated-IP server us2943.nordvpn.com."]
        assert key_cache_path().read_text().strip() == KEY
        assert server_cache_path().read_text().strip() == "us2943.nordvpn.com"

    @patch("ai_shell.vpn.exit_address", return_value="203.0.113.9")
    def test_status_and_remove(self, mock_exit, isolate_home):
        manager = self._manager(MagicMock(status="running"), status="running")
        firewall_off_marker().parent.mkdir(parents=True)
        server_cache_path().write_text("us2943.nordvpn.com\n")
        with patch.dict("os.environ", {}, clear=False):
            assert vpn_status(manager) == {
                "status": "running",
                "exit_address": "203.0.113.9",
                "proxy": "http://127.0.0.1:8888",
                "server": "us2943.nordvpn.com",
            }
        firewall_off_marker().write_text("x")
        assert remove_vpn(manager) is True
        manager.remove_container.assert_called_once_with(VPN_CONTAINER)
        assert not firewall_off_marker().exists()
        assert not server_cache_path().exists()
        assert remove_vpn(self._manager()) is False
