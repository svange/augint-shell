"""Tests for the T3 Code integration."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ai_shell import t3
from ai_shell.config import AiShellConfig
from ai_shell.defaults import (
    T3_CONTAINER_PORT,
    T3_HOME_PATH,
    T3_TOOLS_PATH,
    T3_TOOLS_VOLUME,
    build_dev_mounts,
    t3_home_volume_name,
)

CONTAINER = "augint-shell-demo-dev"


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _config(tmp_path):
    return AiShellConfig(project_name="demo", project_dir=tmp_path)


class TestMounts:
    def test_t3_home_volume_is_per_project(self, tmp_path):
        one = t3_home_volume_name(tmp_path / "a", "app")
        two = t3_home_volume_name(tmp_path / "b", "app")
        assert one != two
        assert one.startswith("augint-shell-t3-")

    def test_dev_mounts_include_t3_home_and_tools(self, tmp_path):
        mounts = build_dev_mounts(tmp_path, "demo")
        targets = {m["Target"]: m for m in mounts}

        assert targets[T3_HOME_PATH]["Source"] == t3_home_volume_name(tmp_path, "demo")
        assert targets[T3_HOME_PATH]["Type"] == "volume"
        assert targets[T3_TOOLS_PATH]["Source"] == T3_TOOLS_VOLUME

    def test_host_t3_dir_is_never_bind_mounted(self, tmp_path):
        """A host T3 install and the container servers must not share a database."""
        mounts = build_dev_mounts(tmp_path, "demo")
        assert all(m["Type"] == "volume" for m in mounts if m["Target"] == T3_HOME_PATH)


class TestCli:
    def test_ensure_cli_skips_install_when_present(self):
        with patch.object(t3, "_exec", return_value=_completed(0)) as mock_exec:
            t3.ensure_cli(CONTAINER)
        assert mock_exec.call_count == 1

    def test_ensure_cli_installs_when_missing(self):
        with patch.object(t3, "_exec", side_effect=[_completed(1), _completed(0)]) as mock_exec:
            t3.ensure_cli(CONTAINER)
        install_args = mock_exec.call_args_list[1][0][1]
        assert "npm install -g t3" in install_args[-1]

    def test_ensure_cli_raises_on_install_failure(self):
        with patch.object(t3, "_exec", side_effect=[_completed(1), _completed(1, stderr="EACCES")]):
            with pytest.raises(t3.T3Error, match="EACCES"):
                t3.ensure_cli(CONTAINER)


class TestServer:
    def test_server_running_probes_well_known_path(self):
        with patch.object(t3, "_exec", return_value=_completed(0)) as mock_exec:
            assert t3.server_running(CONTAINER) is True
        args = mock_exec.call_args[0][1]
        assert f"http://127.0.0.1:{T3_CONTAINER_PORT}/.well-known/t3/environment" in args

    def test_server_running_false_on_probe_failure(self):
        with patch.object(t3, "_exec", return_value=_completed(7)):
            assert t3.server_running(CONTAINER) is False

    def test_start_server_pins_host_and_port(self):
        with patch("ai_shell.t3.subprocess.run") as mock_run:
            t3.start_server(CONTAINER, "/root/projects/demo", extra_env={"FOO": "bar"})
        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["docker", "exec", "-d"]
        assert "-e" in cmd and "FOO=bar" in cmd
        script = cmd[-1]
        assert f"t3 serve --host 0.0.0.0 --port {T3_CONTAINER_PORT}" in script
        assert "/root/projects/demo" in script

    def test_wait_until_ready_returns_true_once_up(self):
        with (
            patch.object(t3, "server_running", side_effect=[False, True]),
            patch("ai_shell.t3.time.sleep"),
        ):
            assert t3.wait_until_ready(CONTAINER, timeout=5) is True

    def test_wait_until_ready_times_out(self):
        with (
            patch.object(t3, "server_running", return_value=False),
            patch("ai_shell.t3.time.sleep"),
        ):
            assert t3.wait_until_ready(CONTAINER, timeout=0) is False


class TestPairing:
    def test_mint_pairing_token_parses_token_line(self):
        stdout = "Pairing with T3 (http://172.17.0.2:3773).\n\nToken: abc123\nExpires: later\n"
        with patch.object(t3, "_exec", return_value=_completed(0, stdout=stdout)) as mock_exec:
            assert t3.mint_pairing_token(CONTAINER) == "abc123"
        # t3 runs through a login shell so a non-default npm prefix still resolves.
        assert mock_exec.call_args[0][1][:2] == ["bash", "-lc"]

    def test_mint_pairing_token_none_on_failure(self):
        with patch.object(t3, "_exec", return_value=_completed(1)):
            assert t3.mint_pairing_token(CONTAINER) is None

    def test_mint_pairing_token_none_when_absent(self):
        with patch.object(t3, "_exec", return_value=_completed(0, stdout="no token here")):
            assert t3.mint_pairing_token(CONTAINER) is None

    def test_add_project_quotes_arguments(self):
        with patch.object(t3, "_exec", return_value=_completed(0)) as mock_exec:
            t3.add_project(CONTAINER, "/root/projects/my demo", "my demo")
        script = mock_exec.call_args[0][1][-1]
        assert "'/root/projects/my demo'" in script

    def test_add_project_tolerates_existing_project(self):
        with patch.object(t3, "_exec", return_value=_completed(1, stderr="already exists")):
            t3.add_project(CONTAINER, "/root/projects/demo", "demo")

    def test_connect_status_parses_json(self):
        with patch.object(t3, "_exec", return_value=_completed(0, stdout='{"linked": true}')):
            assert t3.connect_status(CONTAINER) == {"linked": True}

    def test_connect_status_none_on_bad_json(self):
        with patch.object(t3, "_exec", return_value=_completed(0, stdout="not json")):
            assert t3.connect_status(CONTAINER) is None

    def test_render_qr_produces_block_art(self):
        qr = t3.render_qr("http://example.test/pair#token=x")
        assert qr is not None
        assert set(qr) <= {"█", "▀", "▄", " ", "\n"}


class TestAttach:
    def _manager(self, ports):
        manager = MagicMock()
        manager.container_ports.return_value = ports
        return manager

    def test_attach_starts_server_and_prints_lan_pairing_url(self, tmp_path, capsys):
        manager = self._manager({f"{T3_CONTAINER_PORT}/tcp": "0.0.0.0:30497"})
        with (
            patch.object(t3, "ensure_cli"),
            patch.object(t3, "server_running", return_value=False),
            patch.object(t3, "start_server") as mock_start,
            patch.object(t3, "wait_until_ready", return_value=True),
            patch.object(t3, "add_project") as mock_add,
            patch.object(t3, "mint_pairing_token", return_value="tok"),
            patch.object(t3, "connect_status", return_value=None),
            patch.object(t3, "host_lan_ip", return_value="192.168.1.50"),
        ):
            t3.attach(manager, CONTAINER, _config(tmp_path), {"FOO": "bar"})

        mock_start.assert_called_once()
        assert mock_start.call_args[0][1] == "/root/projects/demo"
        assert mock_start.call_args[1]["extra_env"] == {"FOO": "bar"}
        mock_add.assert_called_once_with(CONTAINER, "/root/projects/demo", "demo")

        captured = capsys.readouterr()
        assert "http://192.168.1.50:30497/pair#token=tok" in captured.err
        # The QR goes to stdout raw so rich never reinterprets the block art.
        assert "█" in captured.out

    def test_attach_reuses_running_server(self, tmp_path):
        manager = self._manager({f"{T3_CONTAINER_PORT}/tcp": "0.0.0.0:30497"})
        with (
            patch.object(t3, "ensure_cli"),
            patch.object(t3, "server_running", return_value=True),
            patch.object(t3, "start_server") as mock_start,
            patch.object(t3, "add_project"),
            patch.object(t3, "mint_pairing_token", return_value="tok"),
            patch.object(t3, "connect_status", return_value=None),
            patch.object(t3, "host_lan_ip", return_value=None),
        ):
            t3.attach(manager, CONTAINER, _config(tmp_path))
        mock_start.assert_not_called()

    def test_attach_raises_when_server_never_answers(self, tmp_path):
        manager = self._manager({})
        with (
            patch.object(t3, "ensure_cli"),
            patch.object(t3, "server_running", return_value=False),
            patch.object(t3, "start_server"),
            patch.object(t3, "wait_until_ready", return_value=False),
            patch.object(t3, "server_log_tail", return_value="boom"),
        ):
            with pytest.raises(t3.T3Error, match="boom"):
                t3.attach(manager, CONTAINER, _config(tmp_path))

    def test_attach_warns_when_port_not_published(self, tmp_path, capsys):
        manager = self._manager({"3000/tcp": "0.0.0.0:26404"})
        with (
            patch.object(t3, "ensure_cli"),
            patch.object(t3, "server_running", return_value=True),
            patch.object(t3, "add_project"),
            patch.object(t3, "mint_pairing_token", return_value="tok"),
            patch.object(t3, "connect_status", return_value=None),
        ):
            t3.attach(manager, CONTAINER, _config(tmp_path))
        err = capsys.readouterr().err
        assert "not published" in err
        assert "ai-shell manage clean" in err


class TestHostLanIp:
    def test_returns_none_when_socket_fails(self):
        with patch("ai_shell.t3.socket.socket", side_effect=OSError):
            assert t3.host_lan_ip() is None


class TestPublishedHostPort:
    def test_reads_live_binding(self):
        manager = MagicMock()
        manager.container_ports.return_value = {"3773/tcp": "0.0.0.0:30497"}
        assert t3._published_host_port(manager, CONTAINER, 3773) == 30497

    def test_none_when_unbound(self):
        manager = MagicMock()
        manager.container_ports.return_value = {}
        assert t3._published_host_port(manager, CONTAINER, 3773) is None

    def test_none_when_container_missing(self):
        manager = MagicMock()
        manager.container_ports.return_value = None
        assert t3._published_host_port(manager, CONTAINER, 3773) is None


class TestPathsUsedByAttach:
    def test_workdir_matches_container_project_mount(self, tmp_path):
        config = _config(tmp_path)
        mounts = build_dev_mounts(Path(tmp_path), config.project_name)
        project_targets = {m["Target"] for m in mounts}
        assert f"/root/projects/{config.project_name}" in project_targets
