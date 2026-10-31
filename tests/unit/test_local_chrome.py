"""Tests for local Chrome bridge (probe + auto-launch + proxy + MCP config)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ai_shell.local_chrome import (
    CHROME_CONTAINER_PROBE_TIMEOUT_SECONDS,
    CHROME_DEBUG_HOST,
    CHROME_HOST_PROBE_TIMEOUT_SECONDS,
    LocalChromeUnavailable,
    _chrome_profile_dir,
    _project_debug_port,
    ensure_host_chrome,
    probe_chrome_port,
    probe_host_chrome_port,
    start_chrome_proxy,
    write_mcp_config,
)


class TestProbeChromePort:
    @patch("ai_shell.local_chrome.subprocess.run")
    def test_returns_true_when_reachable(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"Browser": "Chrome/126.0"}',
        )

        assert probe_chrome_port("augint-shell-test-dev", 9222) is True

        args = mock_run.call_args[0][0]
        assert "docker" in args
        assert "curl" in args
        assert f"http://{CHROME_DEBUG_HOST}:9222/json/version" in args
        # Must include Host: localhost header
        assert "-H" in args
        host_idx = args.index("-H")
        assert "localhost" in args[host_idx + 1]

    @patch("ai_shell.local_chrome.subprocess.run")
    def test_returns_false_when_curl_fails(self, mock_run):
        mock_run.return_value = MagicMock(returncode=7, stdout="")
        assert probe_chrome_port("augint-shell-test-dev", 9222) is False

    @patch("ai_shell.local_chrome.subprocess.run")
    def test_returns_false_when_response_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        assert probe_chrome_port("augint-shell-test-dev", 9222) is False

    @patch("ai_shell.local_chrome.subprocess.run")
    def test_uses_custom_port(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout='{"Browser": "Chrome"}')

        probe_chrome_port("test-dev", 54321)

        args = mock_run.call_args[0][0]
        assert f"http://{CHROME_DEBUG_HOST}:54321/json/version" in args
        host_idx = args.index("-H")
        assert "localhost:54321" in args[host_idx + 1]


class TestProjectChromeState:
    def test_project_debug_port_is_stable(self):
        project_dir = Path("/tmp/project-a")
        port_a = _project_debug_port("project-a", project_dir)
        port_b = _project_debug_port("project-a", project_dir)

        assert port_a == port_b

    def test_project_debug_port_differs_for_different_projects(self):
        port_a = _project_debug_port("project-a", Path("/tmp/project-a"))
        port_b = _project_debug_port("project-b", Path("/tmp/project-b"))

        assert port_a != port_b

    def test_project_profile_dir_is_project_scoped(self):
        profile_a = _chrome_profile_dir("project-a", Path("/tmp/project-a"))
        profile_b = _chrome_profile_dir("project-b", Path("/tmp/project-b"))

        assert profile_a != profile_b
        assert "ai-shell" in profile_a


class TestProbeHostChromePort:
    @patch("ai_shell.local_chrome.HTTPConnection")
    def test_returns_true_when_reachable(self, mock_connection_cls):
        mock_connection = MagicMock()
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"Browser":"Chrome"}'
        mock_connection.getresponse.return_value = response
        mock_connection_cls.return_value = mock_connection

        assert probe_host_chrome_port(9222) is True
        mock_connection_cls.assert_called_once_with("127.0.0.1", 9222, timeout=2)
        mock_connection.request.assert_called_once_with("GET", "/json/version")
        mock_connection.close.assert_called_once()

    @patch("ai_shell.local_chrome.HTTPConnection")
    def test_returns_false_when_unreachable(self, mock_connection_cls):
        mock_connection = MagicMock()
        mock_connection.request.side_effect = OSError("nope")
        mock_connection_cls.return_value = mock_connection

        assert probe_host_chrome_port(9222) is False
        mock_connection.close.assert_called_once()

    @patch("ai_shell.local_chrome.HTTPConnection")
    def test_returns_false_when_http_status_not_ok(self, mock_connection_cls):
        mock_connection = MagicMock()
        response = MagicMock()
        response.status = 500
        response.read.return_value = b'{"error":"boom"}'
        mock_connection.getresponse.return_value = response
        mock_connection_cls.return_value = mock_connection

        assert probe_host_chrome_port(9222) is False
        mock_connection.close.assert_called_once()


class TestEnsureHostChrome:
    @pytest.fixture(autouse=True)
    def _loopback_bind(self):
        """Keep these tests host-independent: the bind address probe shells out."""
        with patch("ai_shell.local_chrome.chrome_bind_address", return_value="127.0.0.1"):
            yield

    @patch("ai_shell.local_chrome._project_debug_port", return_value=54321)
    @patch("ai_shell.local_chrome.probe_chrome_port")
    def test_returns_project_port_when_already_running(self, mock_probe, mock_port):
        mock_probe.return_value = True

        port = ensure_host_chrome("test-dev", project_name="my-project")

        assert port == 54321
        mock_probe.assert_called_once_with("test-dev", 54321)

    @patch("ai_shell.local_chrome._wait_until_ready", side_effect=[True, True])
    @patch("ai_shell.local_chrome.launch_chrome")
    @patch("ai_shell.local_chrome._project_debug_port", return_value=54321)
    @patch("ai_shell.local_chrome.probe_chrome_port", return_value=False)
    def test_launches_chrome_on_project_port(
        self,
        mock_probe,
        mock_port,
        mock_launch,
        mock_wait,
    ):
        mock_launch.return_value = True

        port = ensure_host_chrome(
            "test-dev",
            project_name="my-project",
            project_dir=Path("/tmp/my-project"),
        )

        assert port == 54321
        mock_launch.assert_called_once_with(
            54321,
            project_name="my-project",
            project_dir=Path("/tmp/my-project"),
            profile=None,
            bind_address="127.0.0.1",
        )

    @patch("ai_shell.local_chrome._project_debug_port", return_value=54321)
    @patch("ai_shell.local_chrome.launch_chrome", return_value=False)
    @patch("ai_shell.local_chrome.probe_chrome_port", return_value=False)
    def test_raises_when_chrome_not_found(self, mock_probe, mock_launch, mock_port):
        with pytest.raises(LocalChromeUnavailable, match="could not be found"):
            ensure_host_chrome("test-dev", project_name="my-project")

    @patch("ai_shell.local_chrome._wait_until_ready", side_effect=[False])
    @patch("ai_shell.local_chrome.launch_chrome", return_value=True)
    @patch("ai_shell.local_chrome._project_debug_port", return_value=54321)
    @patch("ai_shell.local_chrome.probe_chrome_port", return_value=False)
    def test_raises_when_host_port_never_opens(
        self,
        mock_probe,
        mock_port,
        mock_launch,
        mock_wait,
    ):
        with pytest.raises(
            LocalChromeUnavailable,
            match=f"127.0.0.1 within {int(CHROME_HOST_PROBE_TIMEOUT_SECONDS)} seconds",
        ):
            ensure_host_chrome("test-dev", project_name="my-project")

    @patch("ai_shell.local_chrome._wait_until_ready", side_effect=[True, False])
    @patch("ai_shell.local_chrome.launch_chrome", return_value=True)
    @patch("ai_shell.local_chrome._project_debug_port", return_value=54321)
    @patch("ai_shell.local_chrome.probe_chrome_port", return_value=False)
    def test_raises_when_container_cannot_reach_host_chrome(
        self,
        mock_probe,
        mock_port,
        mock_launch,
        mock_wait,
    ):
        with pytest.raises(
            LocalChromeUnavailable,
            match=(
                "did not become reachable from the dev container within "
                f"{int(CHROME_CONTAINER_PROBE_TIMEOUT_SECONDS)} seconds"
            ),
        ):
            ensure_host_chrome("test-dev", project_name="my-project")


class TestStartChromeProxy:
    @patch("ai_shell.local_chrome.subprocess.run")
    def test_starts_node_proxy_detached(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        start_chrome_proxy("augint-shell-test-dev", 9222)

        args = mock_run.call_args[0][0]
        assert "docker" in args
        assert "-d" in args
        assert "node" in args
        script = args[args.index("-e") + 1]
        assert "host.docker.internal" in script
        assert "9222" in script

    @patch("ai_shell.local_chrome.subprocess.run")
    def test_uses_custom_port_in_script(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        start_chrome_proxy("test-dev", 54321)

        script = mock_run.call_args[0][0][mock_run.call_args[0][0].index("-e") + 1]
        assert "54321" in script

    @patch("ai_shell.local_chrome.subprocess.run")
    def test_handles_failure_gracefully(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="port in use")
        start_chrome_proxy("test-dev", 9222)  # Should not raise


class TestWriteMcpConfig:
    def test_writes_valid_json_with_localhost_url(self, tmp_path):
        import json

        path = write_mcp_config(9222, config_dir=tmp_path)

        assert path.exists()
        data = json.loads(path.read_text())
        server = data["mcpServers"]["chrome-devtools"]
        assert server["command"] == "npx"
        assert "chrome-devtools-mcp@latest" in server["args"]
        assert "http://localhost:9222" in server["args"]

    def test_uses_custom_port(self, tmp_path):
        import json

        path = write_mcp_config(54321, config_dir=tmp_path)

        data = json.loads(path.read_text())
        assert "http://localhost:54321" in data["mcpServers"]["chrome-devtools"]["args"]

    def test_creates_directory_if_missing(self, tmp_path):
        nested = tmp_path / "deep" / "nested"
        path = write_mcp_config(9222, config_dir=nested)
        assert nested.exists()
        assert path.exists()

    def test_overwrites_existing_file(self, tmp_path):
        (tmp_path / "chrome-mcp.json").write_text("old content")
        path = write_mcp_config(9222, config_dir=tmp_path)
        assert "old content" not in path.read_text()
        assert "mcpServers" in path.read_text()


class TestAccountChromeState:
    def test_account_profile_is_shared_across_projects(self):
        dir_a = _chrome_profile_dir("project-a", Path("/tmp/project-a"), profile="mike")
        dir_b = _chrome_profile_dir("project-b", Path("/tmp/project-b"), profile="mike")
        port_a = _project_debug_port("project-a", Path("/tmp/project-a"), profile="mike")
        port_b = _project_debug_port("project-b", Path("/tmp/project-b"), profile="mike")

        assert dir_a == dir_b
        assert dir_a.endswith("account-mike")
        assert port_a == port_b

    def test_account_profiles_differ_from_each_other_and_from_project(self):
        project_dir = Path("/tmp/project-a")
        mike = _project_debug_port("project-a", project_dir, profile="mike")
        adam = _project_debug_port("project-a", project_dir, profile="adam")
        project = _project_debug_port("project-a", project_dir)

        assert len({mike, adam, project}) == 3
        assert _chrome_profile_dir("project-a", project_dir, profile="Mike_B") != (
            _chrome_profile_dir("project-a", project_dir)
        )

    def test_account_slug_is_sanitized(self):
        assert _chrome_profile_dir("p", None, profile="Mike B!").endswith("account-mike-b")

    def test_mcp_server_spec_points_at_proxy(self):
        from ai_shell.local_chrome import chrome_mcp_server_spec

        spec = chrome_mcp_server_spec(54321)
        assert spec["command"] == "npx"
        assert "http://localhost:54321" in spec["args"]  # type: ignore[operator]


class TestFindChromeAcrossPlatforms:
    @patch("ai_shell.local_chrome.shutil.which")
    @patch("ai_shell.local_chrome.platform.system", return_value="Linux")
    def test_linux_uses_path_lookup_in_preference_order(self, mock_system, mock_which):
        from ai_shell.local_chrome import find_chrome

        mock_which.side_effect = lambda name: "/usr/bin/chromium" if name == "chromium" else None
        assert find_chrome() == "/usr/bin/chromium"
        tried = [c[0][0] for c in mock_which.call_args_list]
        assert tried[:2] == ["google-chrome", "google-chrome-stable"]

    @patch("ai_shell.local_chrome.shutil.which", return_value=None)
    @patch("ai_shell.local_chrome.platform.system", return_value="Linux")
    def test_linux_none_when_nothing_on_path(self, mock_system, mock_which):
        from ai_shell.local_chrome import find_chrome

        assert find_chrome() is None

    @patch("ai_shell.local_chrome.Path.exists", return_value=True)
    @patch("ai_shell.local_chrome.platform.system", return_value="Darwin")
    def test_macos_uses_app_bundle(self, mock_system, mock_exists):
        from ai_shell.local_chrome import find_chrome

        assert find_chrome() == "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class TestChromeBindAddress:
    @patch("ai_shell.local_chrome.platform.system", return_value="Windows")
    def test_loopback_on_docker_desktop_hosts(self, mock_system):
        from ai_shell.local_chrome import chrome_bind_address

        assert chrome_bind_address("c") == "127.0.0.1"

    @patch("ai_shell.local_chrome.subprocess.run")
    @patch("ai_shell.local_chrome.platform.system", return_value="Linux")
    def test_linux_binds_to_the_address_the_container_resolves(self, mock_system, mock_run):
        from ai_shell.local_chrome import chrome_bind_address

        mock_run.return_value = MagicMock(
            returncode=0, stdout="172.17.0.1      host.docker.internal\n"
        )
        assert chrome_bind_address("augint-shell-demo-dev") == "172.17.0.1"
        args = mock_run.call_args[0][0]
        assert args[:3] == ["docker", "exec", "augint-shell-demo-dev"]
        assert args[-1] == "host.docker.internal"

    @patch("ai_shell.local_chrome.subprocess.run")
    @patch("ai_shell.local_chrome.platform.system", return_value="Linux")
    def test_linux_falls_back_to_loopback_when_unresolvable(self, mock_system, mock_run):
        from ai_shell.local_chrome import chrome_bind_address

        mock_run.return_value = MagicMock(returncode=2, stdout="")
        assert chrome_bind_address("c") == "127.0.0.1"


class TestLaunchChromeArgs:
    @patch("ai_shell.local_chrome.subprocess.Popen")
    @patch("ai_shell.local_chrome.find_chrome", return_value="/usr/bin/google-chrome")
    @patch("ai_shell.local_chrome.platform.system", return_value="Linux")
    def test_linux_launch_binds_requested_address_and_detaches(
        self, mock_system, mock_find, mock_popen
    ):
        from ai_shell.local_chrome import launch_chrome

        assert (
            launch_chrome(40001, project_name="p", profile="mike", bind_address="172.17.0.1")
            is True
        )
        args = mock_popen.call_args[0][0]
        assert "--remote-debugging-address=172.17.0.1" in args
        assert "--remote-debugging-port=40001" in args
        assert any(a.endswith("account-mike") for a in args if a.startswith("--user-data-dir="))
        assert "--no-first-run" in args
        assert mock_popen.call_args[1]["start_new_session"] is True
        assert "creationflags" not in mock_popen.call_args[1]
