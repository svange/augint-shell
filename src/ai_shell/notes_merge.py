"""Merge institutional notes into AI tool context files on scaffold/update.

Instead of writing the knowledge file to disk only, invoke the AI tool to merge
institutional knowledge into the tool's context file (CLAUDE.md or AGENTS.md).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tomllib
from importlib import resources
from pathlib import Path
from subprocess import DEVNULL

from rich.console import Console

logger = logging.getLogger(__name__)
console = Console(stderr=True)

_TEMPLATES = resources.files("ai_shell.templates")

_TOOL_CONFIG: dict[str, tuple[str, str]] = {
    "claude": ("CLAUDE.md", "claude"),
    "codex": ("AGENTS.md", "codex"),
    "opencode": ("AGENTS.md", "codex"),
}

_MERGE_TIMEOUT = 120
_NOTES_TEMPLATE_BY_REPO_TYPE = {
    "library": "notes-library.md",
    "service": "notes-service.md",
    "workspace": "notes-workspace.md",
}


def _read_persisted_project(target_dir: Path) -> dict[str, str]:
    """Read [project] section from existing ai-shell.toml, if any."""
    try:
        toml_path = target_dir / "ai-shell.toml"
        if not toml_path.exists():
            return {}
        with open(toml_path, "rb") as handle:
            data = tomllib.load(handle)
        result: dict[str, str] = data.get("project", {})
        return result
    except (OSError, tomllib.TOMLDecodeError, TypeError):
        return {}


def _read_notes_template(target_dir: Path) -> str:
    """Load the generic or repo-specific institutional notes template."""
    project = _read_persisted_project(target_dir)
    template_name = _NOTES_TEMPLATE_BY_REPO_TYPE.get(project.get("repo_type"), "notes.md")
    ref = _TEMPLATES.joinpath(template_name)
    return ref.read_text(encoding="utf-8")


def _build_prompt(context_file: str, notes_content: str) -> str:
    """Build an idempotent merge prompt for agent context files."""
    return (
        f"Merge the institutional notes below into {context_file}. "
        "Treat them as shared workflow and policy guidance, not as a project summary template. "
        "Integrate only net-new or materially changed guidance. "
        "Keep existing project-specific content and local architecture notes intact. "
        "Do not duplicate existing guidance, do not restate the same rule with stronger wording, "
        "and do not make repeated updates more prominent just because this merge runs again. "
        "If equivalent guidance already exists, leave it alone unless the notes below clearly supersede it. "
        "If nothing needs changing, make no changes.\n\n"
        f"{notes_content}"
    )


def _build_command(binary: str, prompt: str) -> list[str]:
    if binary == "claude":
        return ["claude", "-p", prompt, "--dangerously-skip-permissions"]
    if binary == "codex":
        return ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", prompt]
    return []


def merge_notes_into_context(target_dir: Path, tool: str, *, background: bool = False) -> bool:
    """Merge notes template into the tool's context file using the AI tool."""
    config = _TOOL_CONFIG.get(tool)
    if config is None:
        logger.debug("No merge config for tool %r, skipping", tool)
        return False

    context_file, binary = config
    context_path = target_dir / context_file

    if not context_path.exists():
        context_path.write_text(f"# {context_file}\n", encoding="utf-8", newline="\n")
        console.print(
            f"[bold]Created {context_file}; merging institutional notes in background...[/bold]"
        )

    if not shutil.which(binary):
        console.print(f"[yellow]{binary} not found on PATH, skipping {context_file} merge[/yellow]")
        return False

    notes_content = _read_notes_template(target_dir)
    prompt = _build_prompt(context_file, notes_content)
    cmd = _build_command(binary, prompt)

    if background:
        console.print(
            f"[bold]{context_file} merge started in background, file should update shortly.[/bold]"
        )
        subprocess.Popen(cmd, cwd=target_dir, stdout=DEVNULL, stderr=DEVNULL)  # noqa: S603
        return True

    console.print(f"[bold]Merging notes into {context_file} via {binary}...[/bold]")
    try:
        result = subprocess.run(cmd, cwd=target_dir, timeout=_MERGE_TIMEOUT)  # noqa: S603
        if result.returncode != 0:
            console.print(
                f"[yellow]{binary} exited with code {result.returncode}, "
                f"{context_file} may not have been updated[/yellow]"
            )
            return False
    except subprocess.TimeoutExpired:
        console.print(f"[yellow]{binary} timed out after {_MERGE_TIMEOUT}s[/yellow]")
        return False
    except FileNotFoundError:
        console.print(f"[yellow]{binary} not found, skipping {context_file} merge[/yellow]")
        return False

    return True
