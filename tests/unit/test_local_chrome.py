"""Tests for local Chrome bridge (probe + auto-launch + proxy + MCP config)."""

from unittest.mock import MagicMock, patch

import pytest

from ai_shell.local_chrome import (
    CHROME_DEBUG_HOST,
    DEFAULT_CHROME_DEBUG_PORT,
    LocalChromeUnavailable,
    ensure_host_chrome,
    probe_chrome_port,
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


class TestEnsureHostChrome:
    @patch("ai_shell.local_chrome.probe_chrome_port")
    def test_returns_default_port_when_already_running(self, mock_probe):
        mock_probe.return_value = True

        port = ensure_host_chrome("test-dev")

        assert port == DEFAULT_CHROME_DEBUG_PORT
        mock_probe.assert_called_once_with("test-dev", DEFAULT_CHROME_DEBUG_PORT)

    @patch("ai_shell.local_chrome.probe_chrome_port")
    @patch("ai_shell.local_chrome.launch_chrome")
    @patch("ai_shell.local_chrome._find_free_port", return_value=54321)
    def test_launches_chrome_on_free_port(self, mock_port, mock_launch, mock_probe):
        # First call (default port) fails, second call (new port) succeeds
        mock_probe.side_effect = [False, True]
        mock_launch.return_value = True

        port = ensure_host_chrome("test-dev")

        assert port == 54321
        mock_launch.assert_called_once_with(54321)

    @patch("ai_shell.local_chrome.probe_chrome_port", return_value=False)
    @patch("ai_shell.local_chrome.launch_chrome", return_value=False)
    @patch("ai_shell.local_chrome._find_free_port", return_value=54321)
    def test_raises_when_chrome_not_found(self, mock_port, mock_launch, mock_probe):
        with pytest.raises(LocalChromeUnavailable, match="could not be found"):
            ensure_host_chrome("test-dev")


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
