"""Unit tests for GUI display forwarding (--gui) and dev container GPU passthrough (--gpu)."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from ai_shell.cli.__main__ import cli
from ai_shell.config import AiShellConfig, load_config
from ai_shell.container import ContainerManager
from ai_shell.gui import DEFAULT_X11_FALLBACK_DISPLAY, resolve_gui_spec


class TestResolveGuiSpec:
    def test_explicit_display_override(self) -> None:
        spec = resolve_gui_spec("host.docker.internal:1.0")
        assert spec.backend == "x11-tcp"
        assert spec.environment == {"DISPLAY": "host.docker.internal:1.0"}
        assert spec.mounts == []
        assert spec.devices == []
        assert spec.warning is None

    def test_wsl2_wslg_with_d3d12_gpu_bridge(self, tmp_path: Path) -> None:
        wslg = tmp_path / "wslg"
        (wslg / ".X11-unix").mkdir(parents=True)
        wsl_lib = tmp_path / "wsl-lib"
        wsl_lib.mkdir()
        dxg = tmp_path / "dxg"
        dxg.write_text("")

        with (
            patch("ai_shell.gui.sys.platform", "linux"),
            patch("ai_shell.gui.WSLG_ROOT", wslg),
            patch("ai_shell.gui.WSLG_X11_SOCKET", wslg / ".X11-unix"),
            patch("ai_shell.gui.WSLG_LIB_DIR", wsl_lib),
            patch("ai_shell.gui.WSLG_DXG_DEVICE", dxg),
            patch.dict("os.environ", {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}, clear=True),
        ):
            spec = resolve_gui_spec()

        assert spec.backend == "wslg"
        assert spec.warning is None
        targets = {m["Target"] for m in spec.mounts}
        assert "/tmp/.X11-unix" in targets
        assert "/mnt/wslg" in targets
        assert str(wsl_lib) in targets
        assert spec.devices == [f"{dxg}:{dxg}"]
        assert spec.environment["DISPLAY"] == ":0"
        assert spec.environment["WAYLAND_DISPLAY"] == "wayland-0"
        assert spec.environment["XDG_RUNTIME_DIR"] == "/mnt/wslg/runtime-dir"
        assert spec.environment["PULSE_SERVER"] == "/mnt/wslg/PulseServer"
        assert spec.environment["GALLIUM_DRIVER"] == "d3d12"
        assert spec.environment["LD_LIBRARY_PATH"] == str(wsl_lib)

    def test_windows11_uses_wslg_when_no_x11_tcp_server(self) -> None:
        with (
            patch("ai_shell.gui.sys.platform", "win32"),
            patch("ai_shell.gui._x11_tcp_port_open", return_value=False),
            patch("ai_shell.gui._windows_build_number", return_value=22631),
        ):
            spec = resolve_gui_spec()

        assert spec.backend == "wslg"
        assert spec.warning is None
        assert {m["Target"] for m in spec.mounts} == {"/tmp/.X11-unix", "/mnt/wslg"}
        assert spec.environment["DISPLAY"] == ":0"
        assert spec.environment["WAYLAND_DISPLAY"] == "wayland-0"

    def test_windows_prefers_local_x11_server_when_listening(self) -> None:
        with (
            patch("ai_shell.gui.sys.platform", "win32"),
            patch("ai_shell.gui._x11_tcp_port_open", return_value=True),
        ):
            spec = resolve_gui_spec()

        assert spec.backend == "x11-tcp"
        assert spec.environment == {"DISPLAY": DEFAULT_X11_FALLBACK_DISPLAY}
        assert spec.mounts == []
        assert spec.warning is None

    def test_windows10_falls_back_to_x11_tcp_with_warning(self) -> None:
        with (
            patch("ai_shell.gui.sys.platform", "win32"),
            patch("ai_shell.gui._x11_tcp_port_open", return_value=False),
            patch("ai_shell.gui._windows_build_number", return_value=19045),
        ):
            spec = resolve_gui_spec()

        assert spec.backend == "x11-tcp"
        assert spec.environment == {"DISPLAY": DEFAULT_X11_FALLBACK_DISPLAY}
        assert spec.warning is not None
        assert "Windows 11" in spec.warning

    def test_linux_native_x11_and_wayland(self, tmp_path: Path) -> None:
        x11_dir = tmp_path / "X11-unix"
        x11_dir.mkdir()
        runtime_dir = tmp_path / "runtime"
        runtime_dir.mkdir()
        (runtime_dir / "wayland-0").write_text("")
        dri = tmp_path / "dri"
        dri.mkdir()

        with (
            patch("ai_shell.gui.sys.platform", "linux"),
            patch("ai_shell.gui.WSLG_ROOT", tmp_path / "no-wslg"),
            patch("ai_shell.gui.LINUX_X11_SOCKET", x11_dir),
            patch("ai_shell.gui.LINUX_DRI_DEVICE", dri),
            patch.dict(
                "os.environ",
                {
                    "DISPLAY": ":1",
                    "WAYLAND_DISPLAY": "wayland-0",
                    "XDG_RUNTIME_DIR": str(runtime_dir),
                },
                clear=True,
            ),
        ):
            spec = resolve_gui_spec()

        assert spec.backend == "x11"
        assert spec.warning is None
        assert spec.environment["DISPLAY"] == ":1"
        assert spec.environment["WAYLAND_DISPLAY"] == "wayland-0"
        assert spec.devices == [f"{dri}:{dri}"]
        targets = {m["Target"] for m in spec.mounts}
        assert "/tmp/.X11-unix" in targets
        assert "/run/user/0/wayland-0" in targets

    def test_linux_headless_falls_back_with_warning(self, tmp_path: Path) -> None:
        with (
            patch("ai_shell.gui.sys.platform", "linux"),
            patch("ai_shell.gui.WSLG_ROOT", tmp_path / "no-wslg"),
            patch.dict("os.environ", {}, clear=True),
        ):
            spec = resolve_gui_spec()

        assert spec.backend == "x11-tcp"
        assert spec.environment == {"DISPLAY": DEFAULT_X11_FALLBACK_DISPLAY}
        assert spec.warning is not None

    def test_macos_falls_back_with_warning(self) -> None:
        with patch("ai_shell.gui.sys.platform", "darwin"):
            spec = resolve_gui_spec()

        assert spec.backend == "x11-tcp"
        assert spec.environment == {"DISPLAY": DEFAULT_X11_FALLBACK_DISPLAY}
        assert spec.warning is not None


class TestGuiGpuConfigAndContainer:
    def test_config_yaml_and_env_vars(self, tmp_path: Path) -> None:
        (tmp_path / ".ai-shell.yaml").write_text(
            "container:\n  gui: true\n  gui_display: 'host.docker.internal:0.0'\n  gpu: true\n",
            encoding="utf-8",
        )
        with patch.dict("os.environ", {}, clear=True):
            cfg = load_config(project_dir=tmp_path)
        assert cfg.gui is True
        assert cfg.gui_display == "host.docker.internal:0.0"
        assert cfg.gpu is True

        with patch.dict(
            "os.environ",
            {"AI_SHELL_GUI": "0", "AI_SHELL_GUI_DISPLAY": ":2", "AI_SHELL_GPU": "0"},
            clear=True,
        ):
            cfg2 = load_config(project_dir=tmp_path)
        assert cfg2.gui is False
        assert cfg2.gui_display == ":2"
        assert cfg2.gpu is False

    def test_dev_config_digest_changes_on_gui_or_gpu(self, tmp_path: Path) -> None:
        client = MagicMock()
        with patch("docker.from_env", return_value=client):
            base = ContainerManager(AiShellConfig(project_dir=tmp_path, project_name="p"))
            gui_on = ContainerManager(
                AiShellConfig(project_dir=tmp_path, project_name="p", gui=True)
            )
            gpu_on = ContainerManager(
                AiShellConfig(project_dir=tmp_path, project_name="p", gpu=True)
            )
        assert base._dev_config_digest() != gui_on._dev_config_digest()
        assert base._dev_config_digest() != gpu_on._dev_config_digest()
        assert gui_on._dev_config_digest() != gpu_on._dev_config_digest()

    def test_create_dev_container_wires_gui_and_gpu(self, tmp_path: Path) -> None:
        client = MagicMock()
        client.containers.run.return_value = MagicMock()
        cfg = AiShellConfig(
            project_dir=tmp_path,
            project_name="proj",
            gui=True,
            gui_display="host.docker.internal:0.0",
            gpu=True,
        )
        with (
            patch("docker.from_env", return_value=client),
            patch("ai_shell.container.detect_gpu", return_value=True),
        ):
            mgr = ContainerManager(cfg)
            mgr._create_dev_container("augint-shell-proj-dev")

        kwargs = client.containers.run.call_args.kwargs
        assert kwargs["environment"]["DISPLAY"] == "host.docker.internal:0.0"
        assert len(kwargs["device_requests"]) == 1
        assert kwargs["device_requests"][0]["Capabilities"] == [["gpu"]]

    def test_create_dev_container_warns_when_gpu_unavailable(
        self, tmp_path: Path, caplog: logging.LogCaptureFixture
    ) -> None:
        client = MagicMock()
        client.containers.run.return_value = MagicMock()
        cfg = AiShellConfig(project_dir=tmp_path, project_name="proj", gpu=True)
        with (
            caplog.at_level(logging.WARNING),
            patch("docker.from_env", return_value=client),
            patch("ai_shell.container.detect_gpu", return_value=False),
        ):
            mgr = ContainerManager(cfg)
            mgr._create_dev_container("augint-shell-proj-dev")

        kwargs = client.containers.run.call_args.kwargs
        assert "device_requests" not in kwargs
        assert "continuing on CPU" in caplog.text

    def test_cli_shell_accepts_gui_and_gpu_flags(self, tmp_path: Path) -> None:
        captured: dict[str, object] = {}

        def _fake_cm(cfg: AiShellConfig) -> MagicMock:
            captured["gui"] = cfg.gui
            captured["gui_display"] = cfg.gui_display
            captured["gpu"] = cfg.gpu
            m = MagicMock()
            m.ensure_dev_container.return_value = "augint-shell-test-dev"
            m.get_dev_ports.return_value = {}
            return m

        runner = CliRunner()
        with (
            patch("ai_shell.cli.commands.tools.ContainerManager", side_effect=_fake_cm),
            patch("ai_shell.cli.commands.tools.Path.cwd", return_value=tmp_path),
        ):
            result = runner.invoke(
                cli,
                ["shell", "--gui", "--gui-display", "host.docker.internal:0.0", "--gpu"],
            )
        assert result.exit_code == 0, result.output
        assert captured == {
            "gui": True,
            "gui_display": "host.docker.internal:0.0",
            "gpu": True,
        }
