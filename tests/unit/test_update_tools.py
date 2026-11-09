"""docker/update-tools.sh: the npm tools are reinstalled only when one is behind.

`npm install -g <pkg>@latest` relinks every bin of the named packages under
/usr/bin while it runs, even when nothing changed, and a Claude Code session
that starts in that window finds its MCP server binary missing. The script
therefore asks npm for the installed and the latest versions first and skips
the install when they agree. The tests run the script with a fake `npm` on
PATH and the state and log directories moved into a temporary directory.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "docker" / "update-tools.sh"
NPM_TOOLS = [
    "aws-cdk",
    "@playwright/cli",
    "agent-browser",
    "zapier-platform-cli",
    "chrome-devtools-mcp",
    "@agentclientprotocol/claude-agent-acp",
    "@agentclientprotocol/codex-acp",
]
OTHER_TOOLS = ["claude", "codex", "opencode", "pi", "t3"]

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("jq") is None,
    reason="update-tools.sh needs bash and jq",
)

FAKE_NPM = """#!/usr/bin/env bash
# A stand-in npm: records every call, answers `ls -g --json` and
# `view <pkg> version` from the fixture files the test wrote.
echo "$*" >> "$FAKE_NPM_CALLS"
case "$1" in
  ls) cat "$FAKE_NPM_INSTALLED" ;;
  view) jq -r --arg p "$2" '.[$p] // empty' "$FAKE_NPM_LATEST" ;;
  install) exit 0 ;;
  *) exit 1 ;;
esac
"""


def _run(tmp_path: Path, installed: dict[str, str], latest: dict[str, str]) -> list[str]:
    """Run `update-tools.sh --tool npm-tools` against the fake npm; return npm's calls."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    npm = bin_dir / "npm"
    npm.write_text(FAKE_NPM)
    npm.chmod(npm.stat().st_mode | stat.S_IXUSR)
    installed_file = tmp_path / "installed.json"
    installed_file.write_text(
        json.dumps({"dependencies": {p: {"version": v} for p, v in installed.items()}})
    )
    latest_file = tmp_path / "latest.json"
    latest_file.write_text(json.dumps(latest))
    calls = tmp_path / "calls.log"
    state = tmp_path / "state"
    markers = state / "update-markers"
    markers.mkdir(parents=True)
    # Every other tool is fresh, so the background pass has nothing to do.
    for tool in OTHER_TOOLS:
        (markers / f"{tool}.timestamp").write_text(str(int(time.time())))
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "FAKE_NPM_CALLS": str(calls),
        "FAKE_NPM_INSTALLED": str(installed_file),
        "FAKE_NPM_LATEST": str(latest_file),
        "AI_SHELL_UPDATE_STATE_DIR": str(state),
        "AI_SHELL_UPDATE_LOG_DIR": str(tmp_path / "log"),
        "AI_SHELL_UPDATE_BG_DELAY": "0",
    }
    result = subprocess.run(
        ["bash", str(SCRIPT), "--tool", "npm-tools"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (markers / "npm-tools.timestamp").exists(), "the tool is marked updated either way"
    return calls.read_text().splitlines() if calls.exists() else []


def test_skips_the_install_when_every_npm_tool_is_at_its_latest(tmp_path: Path) -> None:
    versions = dict.fromkeys(NPM_TOOLS, "1.0.0")
    calls = _run(tmp_path, installed=versions, latest=versions)
    assert calls, "npm was asked for the versions"
    assert not [c for c in calls if c.startswith("install")]


def test_installs_when_one_npm_tool_is_behind(tmp_path: Path) -> None:
    installed = dict.fromkeys(NPM_TOOLS, "1.0.0")
    latest = {**installed, "chrome-devtools-mcp": "1.1.0"}
    calls = _run(tmp_path, installed=installed, latest=latest)
    installs = [c for c in calls if c.startswith("install")]
    assert installs == ["install -g " + " ".join(f"{p}@latest" for p in NPM_TOOLS)]


def test_installs_when_a_tool_is_missing_or_npm_cannot_say(tmp_path: Path) -> None:
    installed = {p: "1.0.0" for p in NPM_TOOLS if p != "agent-browser"}
    latest = dict.fromkeys(NPM_TOOLS, "1.0.0")
    calls = _run(tmp_path, installed=installed, latest=latest)
    assert [c for c in calls if c.startswith("install")]
    # No published version at all (offline): install rather than guess.
    calls = _run(tmp_path / "offline", installed=latest, latest={})
    assert [c for c in calls if c.startswith("install")]
