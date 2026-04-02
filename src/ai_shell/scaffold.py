"""Project scaffolding for ai-shell init and tool-specific setup.

Template content lives in ``ai_shell/templates/`` as plain files
(JSON, TOML, Markdown) so they can be edited directly.
"""

from __future__ import annotations

import logging
from importlib import resources
from pathlib import Path

from rich.console import Console

logger = logging.getLogger(__name__)
console = Console(stderr=True)

_TEMPLATES = resources.files("ai_shell.templates")


# ── Helpers ─────────────────────────────────────────────────────────


def _read_template(*parts: str) -> str:
    """Read a template file from the ``ai_shell.templates`` package."""
    ref = _TEMPLATES.joinpath(*parts)
    return ref.read_text(encoding="utf-8")


def _write_file(path: Path, content: str, *, overwrite: bool) -> bool:
    """Write *content* to *path*, creating parent dirs as needed.

    Returns ``True`` if the file was written, ``False`` if skipped.
    """
    if path.exists() and not overwrite:
        console.print(f"[yellow]Skipped (already exists): {path}[/yellow]")
        return False

    label = "Updated" if path.exists() else "Created"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    console.print(f"[green]{label}: {path}[/green]")
    return True


# ── Public API ──────────────────────────────────────────────────────

CLAUDE_COMMAND_FILES = [
    "ai-create-cmd.md",
    "ai-fresh-branch.md",
    "ai-pick-issue.md",
    "ai-repo-health.md",
]


def scaffold_claude(target_dir: Path, *, overwrite: bool = False) -> None:
    """Create ``.claude/`` directory with settings and commands."""
    claude_dir = target_dir / ".claude"
    commands_dir = claude_dir / "commands"

    # settings.json
    _write_file(
        claude_dir / "settings.json",
        _read_template("claude", "settings.json"),
        overwrite=overwrite,
    )

    # command files
    for filename in CLAUDE_COMMAND_FILES:
        _write_file(
            commands_dir / filename,
            _read_template("claude", "commands", filename),
            overwrite=overwrite,
        )

    console.print("[bold green]Claude configuration ready.[/bold green]")


def scaffold_project(target_dir: Path, *, overwrite: bool = False) -> None:
    """Create ``ai-shell.toml`` and ``opencode.json`` in *target_dir*."""
    _write_file(
        target_dir / "ai-shell.toml",
        _read_template("ai-shell.toml"),
        overwrite=overwrite,
    )
    _write_file(
        target_dir / "opencode.json",
        _read_template("opencode.json"),
        overwrite=overwrite,
    )

    console.print("[bold green]Project configuration ready.[/bold green]")
