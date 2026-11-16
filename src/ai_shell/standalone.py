"""Standalone single-file executable support (PyInstaller).

Provides runtime helpers for running ``ai-shell`` as a frozen single-file
binary (where ``sys.frozen`` is set and bundled files live in an ephemeral
``sys._MEIPASS`` directory) and the build CLI used in CI and local builds to
produce standalone executables without requiring ``pip`` or PyPI on target
machines.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

from ai_shell import __version__


def is_frozen() -> bool:
    """Return True when running from a frozen PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def detached_subprocess_env(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str] | None:
    """Environment for a detached child process spawned by a frozen binary.

    A PyInstaller ``--onefile`` executable unpacks its bundled runtime into a
    temporary ``_MEI*`` directory and removes that directory when the parent
    process exits. Setting ``PYINSTALLER_RESET_ENVIRONMENT=1`` ensures any
    detached child process (such as ``ai_shell.cdp_relay``) initializes its own
    independent runtime directory instead of inheriting the expiring one.

    Returns ``None`` when not running from a frozen bundle so callers leave the
    default subprocess environment untouched.
    """
    if not is_frozen():
        return None
    base = os.environ if environ is None else environ
    return {**base, "PYINSTALLER_RESET_ENVIRONMENT": "1"}


def persistent_asset_path(
    bundled_path: Path,
    relative_dest: str,
    *,
    cache_root: Path | None = None,
) -> Path:
    """Return a host-persistent path for an asset that Docker bind-mounts.

    In a standard Python install, *bundled_path* lives inside ``site-packages``
    on disk and can be bind-mounted directly into long-running containers.
    In a frozen ``--onefile`` binary, *bundled_path* lives inside the temporary
    ``_MEI*`` directory that is deleted as soon as the CLI process exits.
    Staging the asset under ``~/.cache/ai-shell/runtime-assets/<version>/``
    keeps bind mounts valid for detached containers and across container
    restarts.
    """
    if not is_frozen() or not bundled_path.exists():
        return bundled_path

    root = (
        cache_root
        if cache_root is not None
        else Path.home() / ".cache" / "ai-shell" / "runtime-assets"
    )
    target = root / __version__ / relative_dest

    if bundled_path.is_dir():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundled_path, target, dirs_exist_ok=True)
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundled_path, target)
    return target


def binary_artifact_name(
    system: str | None = None,
    machine: str | None = None,
) -> str:
    """Return the canonical release artifact filename for the target platform."""
    raw_sys = (system or platform.system()).strip().lower()
    raw_arch = (machine or platform.machine()).strip().lower()

    os_map = {
        "linux": "linux",
        "darwin": "macos",
        "macos": "macos",
        "windows": "windows",
        "win32": "windows",
    }
    arch_map = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }

    norm_os = os_map.get(raw_sys, raw_sys or "unknown")
    norm_arch = arch_map.get(raw_arch, raw_arch or "unknown")
    suffix = ".exe" if norm_os == "windows" else ""
    return f"ai-shell-{norm_os}-{norm_arch}{suffix}"


def default_entry_script() -> Path:
    """Return the path to the CLI entry script used by PyInstaller."""
    return Path(__file__).resolve().parent / "cli" / "__main__.py"


def pyinstaller_args(
    *,
    output: Path | None = None,
    entry_script: Path | None = None,
    workpath: Path | None = None,
    specpath: Path | None = None,
) -> list[str]:
    """Build the PyInstaller argument list for a single-file ``ai-shell`` binary."""
    target = output if output is not None else Path("dist") / "ai-shell"
    script = entry_script if entry_script is not None else default_entry_script()

    name = target.stem if target.suffix.lower() == ".exe" else target.name
    dist_dir = target.parent if str(target.parent) else Path(".")

    args = [
        "--onefile",
        "--clean",
        "--noconfirm",
        "--name",
        name,
        "--distpath",
        str(dist_dir),
        "--collect-submodules",
        "ai_shell",
        "--collect-data",
        "ai_shell",
        "--collect-submodules",
        "rich._unicode_data",
        "--copy-metadata",
        "augint-shell",
    ]
    for mod in (
        "tkinter",
        "_tkinter",
        "pytest",
        "mypy",
        "ruff",
        "semgrep",
        "bandit",
        "pdoc",
    ):
        args.extend(["--exclude-module", mod])
    if workpath is not None:
        args.extend(["--workpath", str(workpath)])
    if specpath is not None:
        args.extend(["--specpath", str(specpath)])
    args.append(str(script))
    return args


def build_standalone_binary(output: Path | None = None) -> Path:
    """Compile ``ai-shell`` into a standalone single-file binary using PyInstaller."""
    import importlib

    try:
        pyinstaller_main = importlib.import_module("PyInstaller.__main__")
    except ImportError as exc:
        raise RuntimeError(
            "PyInstaller is required to build the standalone binary. "
            "Run with: uv run --with pyinstaller python -m ai_shell.standalone"
        ) from exc

    if output is None:
        exe_name = "ai-shell.exe" if platform.system() == "Windows" else "ai-shell"
        target = Path("dist") / exe_name
    else:
        target = output

    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ai-shell-pyinstaller-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        args = pyinstaller_args(
            output=target,
            workpath=tmp_path / "build",
            specpath=tmp_path / "spec",
        )
        pyinstaller_main.run(args)

    expected = target
    if (
        platform.system() == "Windows"
        and expected.suffix.lower() != ".exe"
        and not expected.exists()
        and expected.with_suffix(".exe").exists()
    ):
        expected = expected.with_suffix(".exe")

    if not expected.is_file():
        raise RuntimeError(f"Standalone binary was not created at {expected}")
    return expected


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for building the standalone ``ai-shell`` executable."""
    parser = argparse.ArgumentParser(
        prog="python -m ai_shell.standalone",
        description="Build a standalone single-file ai-shell executable.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output path for the compiled binary (default: dist/ai-shell[.exe]).",
    )
    parser.add_argument(
        "--artifact-name",
        action="store_true",
        help="Print the platform-specific release artifact filename and exit.",
    )
    args = parser.parse_args(argv)

    if args.artifact_name:
        print(binary_artifact_name())
        return 0

    try:
        built = build_standalone_binary(args.output)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Built standalone binary: {built}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
