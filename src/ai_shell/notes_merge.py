"""Merge notes template into AI tool context files on --update.

Instead of writing NOTES.md to disk, invokes the AI tool to intelligently
merge template content into the tool's context file (CLAUDE.md or AGENTS.md).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from importlib import resources
from pathlib import Path

from rich.console import Console

logger = logging.getLogger(__name__)
console = Console(stderr=True)

_TEMPLATES = resources.files("ai_shell.templates")

# (context_file, binary_name)
_TOOL_CONFIG: dict[str, tuple[str, str]] = {
    "claude": ("CLAUDE.md", "claude"),
    "codex": ("AGENTS.md", "codex"),
    "opencode": ("AGENTS.md", "codex"),  # codex as proxy (opencode is a TUI)
}

_MERGE_TIMEOUT = 120  # seconds


def _read_notes_template() -> str:
    ref = _TEMPLATES.joinpath("notes.md")
    return ref.read_text(encoding="utf-8")


def _build_prompt(context_file: str, notes_content: str) -> str:
    return (
        f"Update {context_file} with the following information. "
        f"If all of this information is already in {context_file}, "
        f"do not make changes to {context_file}:\n\n{notes_content}"
    )


def _build_command(binary: str, prompt: str) -> list[str]:
    if binary == "claude":
        return ["claude", "-p", prompt, "--dangerously-skip-permissions"]
    if binary == "codex":
        return ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", prompt]
    return []


def merge_notes_into_context(target_dir: Path, tool: str) -> bool:
    """Merge notes template into the tool's context file using the AI tool.

    Returns ``True`` if merge was attempted, ``False`` if skipped.
    """
    config = _TOOL_CONFIG.get(tool)
    if config is None:
        logger.debug("No merge config for tool %r, skipping", tool)
        return False

    context_file, binary = config
    context_path = target_dir / context_file

    if not context_path.exists():
        logger.debug("%s not found, skipping merge", context_file)
        return False

    if not shutil.which(binary):
        console.print(f"[yellow]{binary} not found on PATH, skipping {context_file} merge[/yellow]")
        return False

    notes_content = _read_notes_template()
    prompt = _build_prompt(context_file, notes_content)
    cmd = _build_command(binary, prompt)

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
