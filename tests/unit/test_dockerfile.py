"""Contract tests for docker/Dockerfile and shell configs (dots-bootstrap / dots-doctor parity)."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

DOCKER_DIR = Path(__file__).resolve().parents[2] / "docker"
DOCKERFILE = DOCKER_DIR / "Dockerfile"
ENV_DOCTOR = DOCKER_DIR / "env-doctor.sh"
BASHRC = DOCKER_DIR / "shell-configs" / "bashrc"
ZSHRC = DOCKER_DIR / "shell-configs" / "zshrc"
NVIM_INIT = DOCKER_DIR / "shell-configs" / "nvim-init.vim"


def test_dockerfile_uses_uv_and_pnpm_without_conflicting_global_managers() -> None:
    lines = [
        line
        for line in DOCKERFILE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]
    content = "\n".join(lines)

    # Base image should not ship a conflicting standalone /usr/local/bin/python
    assert "FROM debian:bookworm-slim" in content
    assert "FROM python:" not in content

    # Python should be standardized via uv, not global pip or pyenv/pipx
    assert "uv python install 3.13 --default" in content
    assert "uv tool install" in content
    assert "git-remote-codecommit" in content
    # No global pip: only uv's own `uv pip install` may install a package.
    assert "pip install " not in content.replace("uv pip install ", "")

    # Node.js should be standardized via standalone pnpm, not NodeSource or corepack
    assert "https://get.pnpm.io/install.sh" in content
    assert "pnpm runtime set node lts -g" in content
    assert "deb.nodesource.com" not in content
    assert "corepack" not in content


def test_bedrock_token_library_is_importable_not_a_uv_tool() -> None:
    """Regression: uv refuses `uv tool install` for a package with no command.

    aws-bedrock-token-generator is a library; the image build failed on
    2026-11-20 with "No executables are provided". ai-shell imports it with
    `python3 -c` in the container, so it must be in the managed Python.
    """
    content = DOCKERFILE.read_text(encoding="utf-8")
    assert "uv tool install --python 3.13 aws-bedrock-token-generator" not in content
    assert '--python "$(uv python find --managed-python 3.13)" --system' in content
    assert "--break-system-packages aws-bedrock-token-generator" in content


def test_dockerfile_installs_dots_doctor_and_bootstrap_tools() -> None:
    content = DOCKERFILE.read_text(encoding="utf-8")

    expected_fragments = (
        # dots-doctor checked tools
        "neovim/neovim/releases/latest",
        "zoxide",
        "tcpdump",
        "btop",
        "htop",
        "iproute2",
        "netcat-openbsd",
        "dnsutils",
        "ripgrep",
        "fzf",
        "starship",
        # dots-bootstrap network/system/modern CLI tools
        "tshark",
        "traceroute",
        "mtr-tiny",
        "nmap",
        "lsof",
        "whois",
        "net-tools",
        "duf",
        "lsd",
        "dandavison/delta",
        "jesseduffield/lazygit",
        "sxyazi/yazi",
        "ClementTsang/bottom",
        "dalance/procs",
        "bootandy/dust",
        "fastfetch-cli/fastfetch",
        "mr-karan/doggo",
        "fujiapple852/trippy",
        "orf/gping",
        "ducaale/xh",
        "gitleaks/gitleaks",
        "tldr-pages/tlrc",
        "charmbracelet/glow",
    )
    for fragment in expected_fragments:
        assert fragment in content, f"Missing expected tool in Dockerfile: {fragment}"

    assert NVIM_INIT.is_file()
    assert "COPY shell-configs/nvim-init.vim /root/.config/nvim/init.vim" in content


def test_shell_configs_pass_dots_doctor_and_wire_pnpm_and_zoxide() -> None:
    bashrc = BASHRC.read_text(encoding="utf-8")
    assert "# >>> dots-shell-init >>>" in bashrc
    assert "# <<< dots-shell-init <<<" in bashrc
    assert 'export PNPM_HOME="$HOME/.local/share/pnpm"' in bashrc
    assert 'export PATH="$HOME/.local/bin:$PNPM_HOME/bin:$PNPM_HOME:$PATH"' in bashrc
    assert 'eval "$(zoxide init bash)"' in bashrc
    assert "alias nv='nvim'" in bashrc
    assert "alias lg='lazygit'" in bashrc
    assert "ports()" in bashrc

    zshrc = ZSHRC.read_text(encoding="utf-8")
    assert 'export PNPM_HOME="$HOME/.local/share/pnpm"' in zshrc
    assert 'export PATH="$HOME/.local/bin:$PNPM_HOME/bin:$PNPM_HOME:$PATH"' in zshrc
    assert 'eval "$(zoxide init zsh)"' in zshrc
    assert "\n    pip\n" not in zshrc


@pytest.mark.skipif(shutil.which("sh") is None, reason="env-doctor.sh requires POSIX sh")
def test_env_doctor_installed_and_passes_on_healthy_env(tmp_path: Path) -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "COPY env-doctor.sh /usr/local/bin/env-doctor" in dockerfile
    assert "/usr/local/bin/dots-doctor" not in dockerfile
    assert ENV_DOCTOR.is_file()

    home = tmp_path / "home"
    local_bin = home / ".local" / "bin"
    pnpm_home = home / ".local" / "share" / "pnpm"
    pnpm_bin = pnpm_home / "bin"
    sys_bin = tmp_path / "sysbin"
    for d in (local_bin, pnpm_bin, sys_bin, home / ".ssh", home / ".augint"):
        d.mkdir(parents=True)

    (home / ".bashrc").write_text(BASHRC.read_text(encoding="utf-8"), encoding="utf-8")
    (home / ".augint" / ".env").write_text("FOO=bar\n", encoding="utf-8")

    def _stub(directory: Path, name: str) -> None:
        exe = directory / name
        exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)

    for name in ("uv", "python"):
        _stub(local_bin, name)
    for name in ("pnpm", "node"):
        _stub(pnpm_bin, name)
    for name in (
        "vim",
        "nvim",
        "starship",
        "zoxide",
        "fzf",
        "rg",
        "fd",
        "bat",
        "lsd",
        "delta",
        "lazygit",
        "yazi",
        "jq",
        "yq",
        "dig",
        "doggo",
        "nc",
        "tcpdump",
        "tshark",
        "ip",
        "ss",
        "nmap",
        "mtr",
        "trip",
        "gping",
        "xh",
        "htop",
        "btop",
        "btm",
        "procs",
        "dust",
        "duf",
        "fastfetch",
        "gitleaks",
        "tldr",
        "glow",
        "chezmoi",
    ):
        _stub(sys_bin, name)

    # Keep the test hermetic (host /usr/bin may have pipx, etc.) by symlinking only grep/sed.
    for util in ("grep", "sed"):
        real = shutil.which(util)
        assert real is not None
        (sys_bin / util).symlink_to(real)

    env = {
        "HOME": str(home),
        "PNPM_HOME": str(pnpm_home),
        "PATH": os.pathsep.join([str(local_bin), str(pnpm_bin), str(pnpm_home), str(sys_bin)]),
    }
    sh_bin = shutil.which("sh")
    assert sh_bin is not None
    result = subprocess.run(
        [sh_bin, str(ENV_DOCTOR)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "[env-doctor] Everything looks healthy!" in result.stdout
    assert "Global augint .env present" in result.stdout
