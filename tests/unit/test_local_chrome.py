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
    @patch("ai_shell.local_chrome.urlopen")
    def test_returns_true_when_reachable(self, mock_urlopen):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"Browser":"Chrome"}'
        mock_urlopen.return_value = response

        assert probe_host_chrome_port(9222) is True

    @patch("ai_shell.local_chrome.urlopen", side_effect=OSError("nope"))
    def test_returns_false_when_unreachable(self, mock_urlopen):
        assert probe_host_chrome_port(9222) is False


class TestEnsureHostChrome:
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
            match=f"localhost within {int(CHROME_HOST_PROBE_TIMEOUT_SECONDS)} seconds",
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
