"""Tests for the Expo dev server integration."""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from ai_shell import expo
from ai_shell.config import AiShellConfig
from ai_shell.defaults import DEFAULT_DEV_PORTS, EXPO_METRO_PORT, build_dev_mounts

CONTAINER = "augint-shell-demo-dev"
TUNNEL = "exp://Xf3k2a-anonymous-8081.exp.direct"


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _config(tmp_path):
    return AiShellConfig(project_name="demo", project_dir=tmp_path)


def _write_app(tmp_path, *, dependency=True, app_config="app.json"):
    package = {"name": "demo"}
    if dependency:
        package["dependencies"] = {"expo": "~51.0.0", "react": "18.2.0"}
    (tmp_path / "package.json").write_text(json.dumps(package))
    if app_config == "app.json":
        (tmp_path / "app.json").write_text(json.dumps({"expo": {"name": "demo"}}))
    elif app_config:
        (tmp_path / app_config).write_text("export default {};\n")
    return tmp_path


class TestPorts:
    def test_metro_port_is_published_by_default(self):
        assert EXPO_METRO_PORT in DEFAULT_DEV_PORTS

    def test_expo_home_is_bind_mounted_for_auth_persistence(self, tmp_path):
        mounts = build_dev_mounts(tmp_path, "demo")
        targets = {m["Target"] for m in mounts}
        assert "/root/.expo" in targets


class TestDetect:
    def test_real_app_is_detected(self, tmp_path):
        project = expo.detect(_write_app(tmp_path))
        assert project.is_app
        assert project.app_config == "app.json"

    def test_app_config_js_counts(self, tmp_path):
        project = expo.detect(_write_app(tmp_path, app_config="app.config.ts"))
        assert project.is_app
        assert project.app_config == "app.config.ts"

    def test_dev_dependency_counts(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"devDependencies": {"expo": "*"}}))
        (tmp_path / "app.json").write_text(json.dumps({"expo": {}}))
        assert expo.detect(tmp_path).is_app

    def test_library_without_app_config_is_not_an_app(self, tmp_path):
        project = expo.detect(_write_app(tmp_path, app_config=None))
        assert project.has_dependency
        assert not project.is_app

    def test_app_json_without_expo_key_does_not_count(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"expo": "*"}}))
        (tmp_path / "app.json").write_text(json.dumps({"name": "something-else"}))
        assert not expo.detect(tmp_path).is_app

    def test_non_expo_project_is_not_detected(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "*"}}))
        project = expo.detect(tmp_path)
        assert not project.has_dependency
        assert not project.is_app

    def test_empty_directory_is_not_detected(self, tmp_path):
        assert not expo.detect(tmp_path).has_dependency

    def test_malformed_package_json_is_not_detected(self, tmp_path):
        (tmp_path / "package.json").write_text("{not json")
        assert not expo.detect(tmp_path).has_dependency


class TestNgrok:
    def test_skips_install_when_present(self):
        with patch.object(expo, "_exec", return_value=_completed(0)) as mock_exec:
            expo.ensure_ngrok(CONTAINER)
        assert mock_exec.call_count == 1

    def test_installs_when_missing(self):
        with patch.object(expo, "_exec", side_effect=[_completed(1), _completed(0)]) as mock_exec:
            expo.ensure_ngrok(CONTAINER)
        assert mock_exec.call_count == 2
        assert "npm install -g" in mock_exec.call_args[0][1][2]

    def test_raises_when_install_fails(self):
        with patch.object(expo, "_exec", side_effect=[_completed(1), _completed(1, stderr="nope")]):
            with pytest.raises(expo.ExpoError, match="@expo/ngrok"):
                expo.ensure_ngrok(CONTAINER)


class TestTunnelUrl:
    def test_parses_exp_url_from_log(self):
        log = f"Starting Metro\nTunnel ready.\n› Metro waiting on {TUNNEL}\n"
        with patch.object(expo, "server_log", return_value=log):
            assert expo.tunnel_url(CONTAINER) == TUNNEL

    def test_normalizes_https_origin_to_exp_scheme(self):
        log = "Waiting on https://Xf3k2a-anonymous-8081.exp.direct\n"
        with patch.object(expo, "server_log", return_value=log):
            assert expo.tunnel_url(CONTAINER) == TUNNEL

    def test_last_url_wins(self):
        log = f"exp://old-anonymous-8081.exp.direct\n{TUNNEL}\n"
        with patch.object(expo, "server_log", return_value=log):
            assert expo.tunnel_url(CONTAINER) == TUNNEL

    def test_none_without_a_url(self):
        with patch.object(expo, "server_log", return_value="Starting project...\n"):
            assert expo.tunnel_url(CONTAINER) is None

    def test_lan_url_is_not_mistaken_for_a_tunnel(self):
        with patch.object(expo, "server_log", return_value="exp://192.168.1.10:8081\n"):
            assert expo.tunnel_url(CONTAINER) is None


class TestStartServer:
    def _docker_cmd(self, mock_run):
        return mock_run.call_args[0][0]

    def test_starts_detached_with_tunnel_and_pinned_port(self):
        with patch("subprocess.run") as mock_run:
            expo.start_server(CONTAINER, "/root/projects/demo")
        cmd = self._docker_cmd(mock_run)
        assert cmd[:3] == ["docker", "exec", "-d"]
        script = cmd[-1]
        assert "npx expo start --tunnel" in script
        assert f"--port {EXPO_METRO_PORT}" in script
        assert "cd /root/projects/demo" in script

    def test_truncates_the_log_so_stale_urls_cannot_be_read_back(self):
        with patch("subprocess.run") as mock_run:
            expo.start_server(CONTAINER, "/root/projects/demo")
        script = self._docker_cmd(mock_run)[-1]
        assert f">{expo.EXPO_LOG_PATH}" in script
        assert f">>{expo.EXPO_LOG_PATH}" not in script

    def test_passes_exec_env_and_suppresses_the_cli_qr(self):
        with patch("subprocess.run") as mock_run:
            expo.start_server(CONTAINER, "/root/projects/demo", extra_env={"FOO": "bar"})
        cmd = self._docker_cmd(mock_run)
        assert "FOO=bar" in cmd
        assert "EXPO_NO_QR_CODE=1" in cmd


class TestStartupFailure:
    def test_robot_token_is_explained(self):
        message = expo._startup_failure("CommandError: NGROK_ROBOT ...")
        assert message is not None
        assert "EXPO_TOKEN" in message

    def test_unknown_failure_has_no_special_message(self):
        assert expo._startup_failure("Something else went wrong") is None


class TestAttach:
    def _manager(self):
        manager = MagicMock()
        manager.container_ports.return_value = {f"{EXPO_METRO_PORT}/tcp": "0.0.0.0:14631"}
        return manager

    def test_auto_detection_skips_non_expo_projects(self, tmp_path):
        with patch.object(expo, "start_server") as mock_start:
            expo.attach(self._manager(), CONTAINER, _config(tmp_path))
        mock_start.assert_not_called()

    def test_explicit_flag_errors_on_non_expo_project(self, tmp_path):
        with pytest.raises(expo.ExpoError, match="no 'expo' dependency"):
            expo.attach(self._manager(), CONTAINER, _config(tmp_path), explicit=True)

    def test_auto_detection_skips_a_library(self, tmp_path):
        _write_app(tmp_path, app_config=None)
        with patch.object(expo, "start_server") as mock_start:
            expo.attach(self._manager(), CONTAINER, _config(tmp_path))
        mock_start.assert_not_called()

    def test_missing_container_install_skips_when_auto(self, tmp_path):
        _write_app(tmp_path)
        with (
            patch.object(expo, "dependency_installed", return_value=False),
            patch.object(expo, "start_server") as mock_start,
        ):
            expo.attach(self._manager(), CONTAINER, _config(tmp_path))
        mock_start.assert_not_called()

    def test_missing_container_install_errors_when_explicit(self, tmp_path):
        _write_app(tmp_path)
        with patch.object(expo, "dependency_installed", return_value=False):
            with pytest.raises(expo.ExpoError, match="not installed in the dev container"):
                expo.attach(self._manager(), CONTAINER, _config(tmp_path), explicit=True)

    def test_starts_and_prints_the_tunnel_url(self, tmp_path):
        _write_app(tmp_path)
        with (
            patch.object(expo, "dependency_installed", return_value=True),
            patch.object(expo, "server_running", return_value=False),
            patch.object(expo, "ensure_ngrok") as mock_ngrok,
            patch.object(expo, "start_server") as mock_start,
            patch.object(expo, "wait_for_tunnel", return_value=TUNNEL),
            patch.object(expo.console, "print") as mock_print,
        ):
            expo.attach(self._manager(), CONTAINER, _config(tmp_path))
        mock_ngrok.assert_called_once()
        mock_start.assert_called_once()
        assert any(TUNNEL in str(call) for call in mock_print.call_args_list)

    def test_running_server_is_reused_without_restarting(self, tmp_path):
        _write_app(tmp_path)
        with (
            patch.object(expo, "dependency_installed", return_value=True),
            patch.object(expo, "server_running", return_value=True),
            patch.object(expo, "tunnel_url", return_value=TUNNEL),
            patch.object(expo, "start_server") as mock_start,
            patch.object(expo.console, "print"),
        ):
            expo.attach(self._manager(), CONTAINER, _config(tmp_path))
        mock_start.assert_not_called()

    def test_timeout_raises_with_the_log_tail(self, tmp_path):
        _write_app(tmp_path)
        with (
            patch.object(expo, "dependency_installed", return_value=True),
            patch.object(expo, "server_running", return_value=False),
            patch.object(expo, "ensure_ngrok"),
            patch.object(expo, "start_server"),
            patch.object(expo, "wait_for_tunnel", return_value=None),
            patch.object(expo, "server_log", return_value="NGROK_ROBOT"),
            patch.object(expo.console, "print"),
        ):
            with pytest.raises(expo.ExpoError, match="robot token"):
                expo.attach(self._manager(), CONTAINER, _config(tmp_path))


class TestReusedServerWithoutTunnel:
    def test_running_server_without_a_tunnel_url_is_explained(self, tmp_path):
        _write_app(tmp_path)
        manager = MagicMock()
        manager.container_ports.return_value = {}
        with (
            patch.object(expo, "dependency_installed", return_value=True),
            patch.object(expo, "server_running", return_value=True),
            patch.object(expo, "tunnel_url", return_value=None),
            patch.object(expo, "server_log", return_value="Metro waiting on exp://127.0.0.1:8081"),
            patch.object(expo.console, "print"),
        ):
            with pytest.raises(expo.ExpoError, match="no tunnel URL"):
                expo.attach(manager, CONTAINER, _config(tmp_path))
