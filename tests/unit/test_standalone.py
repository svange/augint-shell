"""Unit tests for standalone PyInstaller executable support (ai_shell.standalone)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ai_shell import __version__, standalone


class TestIsFrozen:
    def test_false_in_normal_interpreter(self):
        with patch.object(sys, "frozen", False, create=True):
            assert standalone.is_frozen() is False

    def test_true_when_sys_frozen_set(self):
        with patch.object(sys, "frozen", True, create=True):
            assert standalone.is_frozen() is True


class TestDetachedSubprocessEnv:
    def test_returns_none_when_not_frozen(self):
        with patch.object(sys, "frozen", False, create=True):
            assert standalone.detached_subprocess_env({"FOO": "bar"}) is None

    def test_adds_pyinstaller_reset_environment_when_frozen(self):
        with patch.object(sys, "frozen", True, create=True):
            env = standalone.detached_subprocess_env({"FOO": "bar"})
            assert env == {"FOO": "bar", "PYINSTALLER_RESET_ENVIRONMENT": "1"}


class TestPersistentAssetPath:
    def test_returns_bundled_path_when_not_frozen(self, tmp_path):
        asset = tmp_path / "provision.sh"
        asset.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
        with patch.object(sys, "frozen", False, create=True):
            result = standalone.persistent_asset_path(
                asset, "comfyui/provision.sh", cache_root=tmp_path / "cache"
            )
        assert result == asset
        assert not (tmp_path / "cache").exists()

    def test_returns_bundled_path_when_missing_even_if_frozen(self, tmp_path):
        missing = tmp_path / "does-not-exist.sh"
        with patch.object(sys, "frozen", True, create=True):
            result = standalone.persistent_asset_path(
                missing, "comfyui/provision.sh", cache_root=tmp_path / "cache"
            )
        assert result == missing

    def test_copies_file_to_versioned_cache_when_frozen(self, tmp_path):
        bundled = tmp_path / "mei" / "provision.sh"
        bundled.parent.mkdir(parents=True)
        bundled.write_text("#!/bin/sh\necho provision\n", encoding="utf-8")
        cache_root = tmp_path / "cache"

        with patch.object(sys, "frozen", True, create=True):
            result = standalone.persistent_asset_path(
                bundled, "comfyui/provision.sh", cache_root=cache_root
            )

        assert result == cache_root / __version__ / "comfyui" / "provision.sh"
        assert result.read_text(encoding="utf-8") == "#!/bin/sh\necho provision\n"

    def test_copies_directory_to_versioned_cache_when_frozen(self, tmp_path):
        bundled_dir = tmp_path / "mei" / "workflows"
        bundled_dir.mkdir(parents=True)
        (bundled_dir / "flow.json").write_text('{"name": "test"}', encoding="utf-8")
        cache_root = tmp_path / "cache"

        with patch.object(sys, "frozen", True, create=True):
            result = standalone.persistent_asset_path(
                bundled_dir, "n8n/workflows", cache_root=cache_root
            )

        assert result == cache_root / __version__ / "n8n" / "workflows"
        assert (result / "flow.json").read_text(encoding="utf-8") == '{"name": "test"}'


class TestBinaryArtifactName:
    @pytest.mark.parametrize(
        ("system", "machine", "expected"),
        [
            ("Linux", "x86_64", "ai-shell-linux-x86_64"),
            ("Linux", "amd64", "ai-shell-linux-x86_64"),
            ("Linux", "aarch64", "ai-shell-linux-arm64"),
            ("Darwin", "arm64", "ai-shell-macos-arm64"),
            ("Darwin", "x86_64", "ai-shell-macos-x86_64"),
            ("Windows", "AMD64", "ai-shell-windows-x86_64.exe"),
            ("win32", "x86_64", "ai-shell-windows-x86_64.exe"),
        ],
    )
    def test_canonical_names(self, system, machine, expected):
        assert standalone.binary_artifact_name(system, machine) == expected


class TestPyInstallerArgs:
    def test_default_arguments_include_required_collections(self):
        args = standalone.pyinstaller_args()
        assert "--onefile" in args
        assert "--clean" in args
        assert "--noconfirm" in args
        assert "--collect-submodules" in args
        assert "ai_shell" in args
        assert "rich._unicode_data" in args
        assert "--collect-data" in args
        assert "--copy-metadata" in args
        assert "augint-shell" in args
        assert args[-1].endswith("cli/__main__.py") or args[-1].endswith(r"cli\__main__.py")

    def test_custom_output_and_workpaths(self, tmp_path):
        out = tmp_path / "bin" / "ai-shell-windows-x86_64.exe"
        work = tmp_path / "work"
        spec = tmp_path / "spec"
        args = standalone.pyinstaller_args(output=out, workpath=work, specpath=spec)

        name_idx = args.index("--name")
        dist_idx = args.index("--distpath")
        work_idx = args.index("--workpath")
        spec_idx = args.index("--specpath")
        assert args[name_idx + 1] == "ai-shell-windows-x86_64"
        assert Path(args[dist_idx + 1]) == tmp_path / "bin"
        assert Path(args[work_idx + 1]) == work
        assert Path(args[spec_idx + 1]) == spec


class TestBuildStandaloneBinary:
    def test_raises_helpful_error_when_pyinstaller_missing(self):
        with (
            patch.dict(sys.modules, {"PyInstaller": None, "PyInstaller.__main__": None}),
            pytest.raises(RuntimeError, match="PyInstaller is required"),
        ):
            standalone.build_standalone_binary()

    def test_invokes_pyinstaller_and_returns_output_path(self, tmp_path):
        output = tmp_path / "out" / "ai-shell"

        def fake_run(args: list[str]) -> None:
            name = args[args.index("--name") + 1]
            dist = Path(args[args.index("--distpath") + 1])
            (dist / name).write_bytes(b"\x7fELF-fake-binary")

        fake_pyi = SimpleNamespace(__main__=SimpleNamespace(run=fake_run))
        with patch.dict(
            sys.modules,
            {"PyInstaller": fake_pyi, "PyInstaller.__main__": fake_pyi.__main__},
        ):
            result = standalone.build_standalone_binary(output)

        assert result == output
        assert result.is_file()

    def test_raises_when_pyinstaller_produces_no_binary(self, tmp_path):
        output = tmp_path / "out" / "ai-shell"
        fake_pyi = SimpleNamespace(__main__=SimpleNamespace(run=lambda _args: None))
        with (
            patch.dict(
                sys.modules,
                {"PyInstaller": fake_pyi, "PyInstaller.__main__": fake_pyi.__main__},
            ),
            pytest.raises(RuntimeError, match="Standalone binary was not created"),
        ):
            standalone.build_standalone_binary(output)


class TestStandaloneCliMain:
    def test_artifact_name_flag_prints_name(self, capsys):
        with patch(
            "ai_shell.standalone.binary_artifact_name", return_value="ai-shell-linux-x86_64"
        ):
            rc = standalone.main(["--artifact-name"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "ai-shell-linux-x86_64"

    def test_build_success(self, tmp_path, capsys):
        out = tmp_path / "ai-shell"
        with patch("ai_shell.standalone.build_standalone_binary", return_value=out) as mock_build:
            rc = standalone.main(["--output", str(out)])
        assert rc == 0
        mock_build.assert_called_once_with(out)
        assert str(out) in capsys.readouterr().out

    def test_build_failure_returns_nonzero(self, capsys):
        with patch(
            "ai_shell.standalone.build_standalone_binary",
            side_effect=RuntimeError("missing pyinstaller"),
        ):
            rc = standalone.main([])
        assert rc == 1
        assert "missing pyinstaller" in capsys.readouterr().err


class TestFrozenIntegrationHooks:
    def test_cli_main_dispatches_cdp_relay_module_flag(self):
        from ai_shell.cli.__main__ import main

        with (
            patch.object(sys, "argv", ["ai-shell", "-m", "ai_shell.cdp_relay", "10.0.0.1", "9222"]),
            patch("ai_shell.cdp_relay.main", return_value=0) as mock_relay,
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 0
        mock_relay.assert_called_once_with(["10.0.0.1", "9222"])

    def test_acp_self_command_uses_sys_executable_when_frozen(self, tmp_path):
        from ai_shell.cli.commands.acp import self_command

        fake_bin = tmp_path / "ai-shell-standalone"
        fake_bin.write_text("", encoding="utf-8")
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", str(fake_bin)),
        ):
            assert self_command() == str(fake_bin.resolve())

    def test_spawn_detached_passes_reset_env_when_frozen(self):
        from ai_shell.local_chrome import _spawn_detached

        with (
            patch.object(sys, "frozen", True, create=True),
            patch("ai_shell.local_chrome.platform.system", return_value="Linux"),
            patch("ai_shell.local_chrome.subprocess.Popen") as mock_popen,
        ):
            _spawn_detached(["/path/to/ai-shell", "-m", "ai_shell.cdp_relay"])
        env = mock_popen.call_args.kwargs.get("env")
        assert env is not None
        assert env.get("PYINSTALLER_RESET_ENVIRONMENT") == "1"
