"""Tests for local Chrome bridge (probe + auto-launch + proxy + MCP config)."""

import os
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
            proxy=None,
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
        assert server["command"] == "chrome-devtools-mcp"
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
        assert spec["command"] == "chrome-devtools-mcp"
        assert spec["args"] == ["--browserUrl", "http://localhost:54321"]


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


class TestChromeProxy:
    @patch("ai_shell.local_chrome.subprocess.Popen")
    @patch("ai_shell.local_chrome.find_chrome", return_value="/usr/bin/google-chrome")
    @patch("ai_shell.local_chrome.platform.system", return_value="Linux")
    def test_launch_passes_proxy_server(self, mock_system, mock_find, mock_popen):
        from ai_shell.local_chrome import launch_chrome

        assert launch_chrome(40001, project_name="p", proxy="http://127.0.0.1:8888") is True
        args = mock_popen.call_args[0][0]
        assert "--proxy-server=http://127.0.0.1:8888" in args
        assert "--remote-debugging-port=40001" in args

    @patch("ai_shell.local_chrome.subprocess.Popen")
    @patch("ai_shell.local_chrome.find_chrome", return_value="/usr/bin/google-chrome")
    @patch("ai_shell.local_chrome.platform.system", return_value="Linux")
    def test_launch_without_proxy_adds_no_flag(self, mock_system, mock_find, mock_popen):
        from ai_shell.local_chrome import launch_chrome

        launch_chrome(40001, project_name="p")
        assert not [a for a in mock_popen.call_args[0][0] if a.startswith("--proxy-server")]

    @patch("ai_shell.local_chrome.chrome_bind_address", return_value="127.0.0.1")
    @patch("ai_shell.local_chrome._wait_until_ready", side_effect=[True, True])
    @patch("ai_shell.local_chrome.launch_chrome", return_value=True)
    @patch("ai_shell.local_chrome._project_debug_port", return_value=54321)
    @patch("ai_shell.local_chrome.probe_chrome_port", return_value=False)
    def test_ensure_hands_proxy_to_launch(
        self, mock_probe, mock_port, mock_launch, mock_wait, mock_bind
    ):
        ensure_host_chrome(
            "test-dev", project_name="p", profile="mike", proxy="socks5://127.0.0.1:1080"
        )
        assert mock_launch.call_args[1]["proxy"] == "socks5://127.0.0.1:1080"

    @patch("ai_shell.local_chrome.chrome_bind_address", return_value="127.0.0.1")
    @patch("ai_shell.local_chrome.launch_chrome", return_value=False)
    @patch("ai_shell.local_chrome.probe_chrome_port", return_value=False)
    def test_manual_instructions_include_proxy(self, mock_probe, mock_launch, mock_bind):
        with pytest.raises(LocalChromeUnavailable, match=r"--proxy-server=http://127.0.0.1:8888"):
            ensure_host_chrome("test-dev", project_name="p", proxy="http://127.0.0.1:8888")


def _staying_up(mock_popen):
    """Make the patched Popen's process survive the start check."""
    import subprocess

    mock_popen.return_value.wait.side_effect = subprocess.TimeoutExpired(cmd="chrome", timeout=2)
    return mock_popen


class TestLaunchPlainChrome:
    """``ai-shell chrome``: the profile's window without the DevTools port."""

    @patch("ai_shell.local_chrome.probe_host_chrome_port", return_value=False)
    @patch("ai_shell.local_chrome.subprocess.Popen")
    @patch("ai_shell.local_chrome.find_chrome", return_value="/usr/bin/google-chrome")
    @patch("ai_shell.local_chrome.platform.system", return_value="Linux")
    def test_opens_profile_without_debug_flags(
        self, mock_system, mock_find, mock_popen, mock_probe
    ):
        from ai_shell.local_chrome import launch_plain_chrome

        _staying_up(mock_popen)
        with patch.dict("os.environ", {"DISPLAY": ":3"}):
            window = launch_plain_chrome(
                project_name="p",
                profile="mike",
                proxy="http://127.0.0.1:8888",
                url="https://accounts.google.com/",
            )
        profile_dir = window.profile_dir
        args = mock_popen.call_args[0][0]
        assert profile_dir.endswith("account-mike")
        assert window.process is mock_popen.return_value
        assert f"--user-data-dir={profile_dir}" in args
        assert "--proxy-server=http://127.0.0.1:8888" in args
        assert args[-1] == "https://accounts.google.com/"
        assert not [a for a in args if a.startswith("--remote-")]
        assert mock_popen.call_args[1]["start_new_session"] is True

    @patch("ai_shell.local_chrome.find_chrome", return_value=None)
    def test_fails_when_chrome_missing(self, mock_find):
        from ai_shell.local_chrome import launch_plain_chrome

        with pytest.raises(LocalChromeUnavailable, match="could not be found"):
            launch_plain_chrome(project_name="p")

    @patch("ai_shell.local_chrome.probe_host_chrome_port", return_value=True)
    @patch("ai_shell.local_chrome.subprocess.Popen")
    @patch("ai_shell.local_chrome.find_chrome", return_value="/usr/bin/google-chrome")
    def test_refuses_while_debug_port_chrome_runs(self, mock_find, mock_popen, mock_probe):
        from ai_shell.local_chrome import launch_plain_chrome

        with pytest.raises(LocalChromeUnavailable, match="already uses the profile"):
            launch_plain_chrome(project_name="p", profile="mike")
        mock_popen.assert_not_called()

    @patch("ai_shell.local_chrome.probe_host_chrome_port", return_value=False)
    @patch("ai_shell.local_chrome.subprocess.Popen")
    @patch("ai_shell.local_chrome.find_chrome", return_value="/usr/bin/google-chrome")
    @patch("ai_shell.local_chrome.platform.system", return_value="Linux")
    def test_refuses_while_profile_lock_is_held(
        self, mock_system, mock_find, mock_popen, mock_probe, tmp_path
    ):
        from ai_shell.local_chrome import launch_plain_chrome

        profile_dir = tmp_path / "account-mike"
        profile_dir.mkdir()
        (profile_dir / "SingletonLock").symlink_to("otherhost-1234")
        with (
            patch("ai_shell.local_chrome._chrome_profile_dir", return_value=str(profile_dir)),
            pytest.raises(LocalChromeUnavailable, match="already uses the profile"),
        ):
            launch_plain_chrome(project_name="p", profile="mike")
        mock_popen.assert_not_called()

    @patch("ai_shell.local_chrome.probe_host_chrome_port", return_value=False)
    @patch("ai_shell.local_chrome.subprocess.Popen")
    @patch("ai_shell.local_chrome.find_chrome", return_value="/usr/bin/google-chrome")
    @patch("ai_shell.local_chrome.platform.system", return_value="Linux")
    def test_refuses_without_a_display(self, mock_system, mock_find, mock_popen, mock_probe):
        from ai_shell.local_chrome import launch_plain_chrome

        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
        with (
            patch.dict("os.environ", env, clear=True),
            pytest.raises(LocalChromeUnavailable, match="no desktop display"),
        ):
            launch_plain_chrome(project_name="p", profile="mike")
        mock_popen.assert_not_called()

    @patch("ai_shell.local_chrome.platform.system", return_value="Windows")
    def test_display_check_is_linux_only(self, mock_system):
        from ai_shell.local_chrome import no_display_reason

        assert no_display_reason({}) is None

    @patch("ai_shell.local_chrome.probe_host_chrome_port", return_value=False)
    @patch("ai_shell.local_chrome.subprocess.Popen")
    @patch("ai_shell.local_chrome.find_chrome", return_value="/usr/bin/google-chrome")
    @patch("ai_shell.local_chrome.platform.system", return_value="Linux")
    def test_chrome_that_exits_at_once_is_an_error_with_its_output(
        self, mock_system, mock_find, mock_popen, mock_probe
    ):
        from ai_shell.local_chrome import launch_plain_chrome

        def popen(args, **kwargs):
            kwargs["stderr"].write(
                b"[1:1:ERROR:ozone_platform_x11.cc] Missing X server or $DISPLAY\n"
            )
            process = MagicMock()
            process.wait.return_value = 1
            return process

        mock_popen.side_effect = popen
        with (
            patch.dict("os.environ", {"DISPLAY": ":3"}),
            pytest.raises(LocalChromeUnavailable, match=r"exited at once \(code 1\)") as info,
        ):
            launch_plain_chrome(project_name="p", profile="mike")
        assert "Missing X server" in str(info.value)

    @patch("ai_shell.local_chrome.platform.system", return_value="Windows")
    def test_lock_check_is_posix_only(self, mock_system, tmp_path):
        from ai_shell.local_chrome import chrome_profile_in_use

        (tmp_path / "SingletonLock").symlink_to("host-1")
        assert chrome_profile_in_use(tmp_path) is False


class TestClosingChrome:
    @patch("ai_shell.local_chrome.close_chrome_profile", return_value=True)
    @patch("ai_shell.local_chrome.probe_host_chrome_port", return_value=True)
    @patch("ai_shell.local_chrome.subprocess.Popen")
    @patch("ai_shell.local_chrome.find_chrome", return_value="/usr/bin/google-chrome")
    @patch("ai_shell.local_chrome.platform.system", return_value="Linux")
    def test_close_running_quits_the_debug_chrome_first(
        self, mock_system, mock_find, mock_popen, mock_probe, mock_close
    ):
        from ai_shell.local_chrome import launch_plain_chrome

        _staying_up(mock_popen)
        with patch.dict("os.environ", {"DISPLAY": ":3"}):
            window = launch_plain_chrome(project_name="p", profile="mike", close_running=True)
        mock_close.assert_called_once()
        assert mock_close.call_args[0][0] == window.profile_dir
        assert mock_close.call_args[0][1] == window.port
        mock_popen.assert_called_once()

    @patch("ai_shell.local_chrome.close_chrome_profile", return_value=False)
    @patch("ai_shell.local_chrome.probe_host_chrome_port", return_value=True)
    @patch("ai_shell.local_chrome.subprocess.Popen")
    @patch("ai_shell.local_chrome.find_chrome", return_value="/usr/bin/google-chrome")
    def test_close_running_that_fails_still_refuses(
        self, mock_find, mock_popen, mock_probe, mock_close
    ):
        from ai_shell.local_chrome import launch_plain_chrome

        with pytest.raises(LocalChromeUnavailable, match="already uses the profile"):
            launch_plain_chrome(project_name="p", profile="mike", close_running=True)
        mock_popen.assert_not_called()

    @patch("ai_shell.local_chrome._wait_until_profile_free", return_value=True)
    @patch("ai_shell.local_chrome.subprocess.run")
    @patch("ai_shell.local_chrome.platform.system", return_value="Linux")
    def test_close_chrome_profile_sends_term_by_profile_dir(self, mock_system, mock_run, mock_wait):
        from ai_shell.local_chrome import close_chrome_profile

        assert close_chrome_profile("/home/u/.config/google-chrome/ai-shell/account-mike", 40001)
        args = mock_run.call_args[0][0]
        assert args[:3] == ["pkill", "-TERM", "-f"]
        assert args[-1].startswith("--user-data-dir=")
        import re

        pattern = args[-1][len("--user-data-dir=") :]
        assert re.fullmatch(pattern, "/home/u/.config/google-chrome/ai-shell/account-mike")
        assert not re.fullmatch(pattern, "/home/u/.config/google-chrome/ai-shell/account-mikey")
        mock_wait.assert_called_once()

    @patch("ai_shell.local_chrome._wait_until_profile_free", return_value=True)
    @patch("ai_shell.local_chrome.platform.system", return_value="Linux")
    def test_plain_chrome_close_terminates_and_waits(self, mock_system, mock_wait):
        from ai_shell.local_chrome import PlainChrome

        process = MagicMock()
        process.poll.return_value = None
        window = PlainChrome(profile_dir="/p", port=40001, process=process)

        assert window.close() is True
        process.terminate.assert_called_once()
        process.wait.assert_called_once()
        mock_wait.assert_called_once_with("/p", 40001, 20.0)

    @patch("ai_shell.local_chrome._wait_until_profile_free", return_value=True)
    def test_plain_chrome_close_skips_a_dead_process(self, mock_wait):
        from ai_shell.local_chrome import PlainChrome

        process = MagicMock()
        process.poll.return_value = 0
        assert PlainChrome(profile_dir="/p", port=1, process=process).close() is True
        process.terminate.assert_not_called()


class _KeptStringIO:
    """Collects writes and keeps them readable after close()."""

    def __init__(self) -> None:
        self.text = ""

    def write(self, data: str) -> int:
        self.text += data
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeProc:
    """A Popen stand-in: stdout yields the given lines, stdin collects writes."""

    def __init__(self, lines: list[str]) -> None:
        self.stdout = iter(lines)
        self.stdin = _KeptStringIO()
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        pass


def _rpc(id_: int, result: dict | None = None, error: dict | None = None) -> str:
    import json

    message: dict = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        message["error"] = error
    else:
        message["result"] = result or {}
    return json.dumps(message) + "\n"


class TestEnsureChromeMcp:
    @patch("ai_shell.local_chrome.subprocess.run")
    def test_skips_install_when_the_binary_exists(self, mock_run):
        from ai_shell.local_chrome import ensure_chrome_mcp

        mock_run.return_value = MagicMock(returncode=0)
        ensure_chrome_mcp("demo-dev")
        assert mock_run.call_count == 1
        assert "command -v chrome-devtools-mcp" in mock_run.call_args[0][0][-1]

    @patch("ai_shell.local_chrome.subprocess.run")
    def test_installs_globally_on_an_older_image(self, mock_run):
        from ai_shell.local_chrome import ensure_chrome_mcp

        mock_run.side_effect = [MagicMock(returncode=1), MagicMock(returncode=0)]
        ensure_chrome_mcp("demo-dev")
        install = mock_run.call_args_list[1][0][0]
        assert install[:3] == ["docker", "exec", "demo-dev"]
        assert "npm install -g chrome-devtools-mcp@latest" in install[-1]

    @patch("ai_shell.local_chrome.subprocess.run")
    def test_failed_install_names_npm_output(self, mock_run):
        from ai_shell.local_chrome import LocalChromeUnavailable, ensure_chrome_mcp

        mock_run.side_effect = [
            MagicMock(returncode=1),
            MagicMock(returncode=1, stderr="EACCES boom", stdout=""),
        ]
        with pytest.raises(LocalChromeUnavailable, match="EACCES boom"):
            ensure_chrome_mcp("demo-dev")


class TestProbeChromeMcp:
    def _probe(self, lines: list[str], **kwargs):
        from ai_shell.local_chrome import probe_chrome_mcp

        proc = _FakeProc(lines)
        with patch("ai_shell.local_chrome.subprocess.Popen", return_value=proc) as popen:
            text = probe_chrome_mcp("demo-dev", 9222, timeout_seconds=2, **kwargs)
        return text, proc, popen

    def test_handshake_then_list_pages_through_the_proxy(self):
        lines = [
            _rpc(1, {"serverInfo": {"name": "chrome-devtools-mcp"}}),
            _rpc(2, {"content": [{"type": "text", "text": "0: about:blank [selected]"}]}),
        ]
        text, proc, popen = self._probe(lines)

        assert text == "0: about:blank [selected]"
        argv = popen.call_args[0][0]
        assert argv[:4] == ["docker", "exec", "-i", "demo-dev"]
        assert argv[-1] == "exec chrome-devtools-mcp --browserUrl http://localhost:9222"
        sent = proc.stdin.text.splitlines()
        assert '"method": "initialize"' in sent[0]
        assert '"method": "notifications/initialized"' in sent[1]
        assert '"name": "list_pages"' in sent[2]
        assert proc.terminated

    def test_tool_error_means_chrome_was_unreachable(self):
        from ai_shell.local_chrome import LocalChromeUnavailable

        lines = [
            _rpc(1, {}),
            _rpc(2, {"isError": True, "content": [{"type": "text", "text": "ECONNREFUSED"}]}),
        ]
        with pytest.raises(LocalChromeUnavailable, match="ECONNREFUSED"):
            self._probe(lines)

    def test_rpc_error_is_reported(self):
        from ai_shell.local_chrome import LocalChromeUnavailable

        lines = [_rpc(1, {}), _rpc(2, error={"code": -32601, "message": "Unknown tool"})]
        with pytest.raises(LocalChromeUnavailable, match="Unknown tool"):
            self._probe(lines)

    def test_silence_is_a_timeout_with_the_server_output(self):
        from ai_shell.local_chrome import LocalChromeUnavailable, probe_chrome_mcp

        proc = _FakeProc([])

        def _popen(*args, **kwargs):
            kwargs["stderr"].write("Error: Cannot find module 'puppeteer-core'\n")
            return proc

        with (
            patch("ai_shell.local_chrome.subprocess.Popen", side_effect=_popen),
            pytest.raises(LocalChromeUnavailable, match="puppeteer-core"),
        ):
            probe_chrome_mcp("demo-dev", 9222, timeout_seconds=0.2)


class TestPrepareChromeMcp:
    @patch("ai_shell.local_chrome.probe_chrome_mcp", return_value="pages")
    @patch("ai_shell.local_chrome.ensure_chrome_mcp")
    def test_installs_then_probes(self, mock_ensure, mock_probe):
        from ai_shell.local_chrome import prepare_chrome_mcp

        assert prepare_chrome_mcp("demo-dev", 9222) == "pages"
        mock_ensure.assert_called_once_with("demo-dev")
        mock_probe.assert_called_once_with("demo-dev", 9222)
