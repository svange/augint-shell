"""Project scaffolding for ai-shell init.

Template content lives in ``ai_shell/templates/`` as plain files
(YAML, TOML) so they can be edited directly.
"""

from __future__ import annotations

import logging
from importlib import resources
from pathlib import Path

from rich.console import Console

logger = logging.getLogger(__name__)
console = Console(stderr=True)

_TEMPLATES = resources.files("ai_shell.templates")

_PROJECT_FILES = [".ai-shell.yaml", ".ai-shell.yml", ".ai-shell.toml", "ai-shell.toml"]


# ── Helpers ─────────────────────────────────────────────────────────


def _read_template(*parts: str) -> str:
    """Read a template file from the ``ai_shell.templates`` package."""
    ref = _TEMPLATES.joinpath(*parts)
    content = ref.read_text(encoding="utf-8")
    return content.replace("\r\n", "\n")


def _write_file(path: Path, content: str, *, overwrite: bool) -> bool:
    """Write *content* to *path*, creating parent dirs as needed.

    Returns ``True`` if the file was written, ``False`` if skipped.
    """
    if path.exists() and not overwrite:
        console.print(f"[yellow]Skipped (already exists): {path}[/yellow]")
        return False

    label = "Updated" if path.exists() else "Created"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    console.print(f"[green]{label}: {path}[/green]")
    return True


# ── Public API ──────────────────────────────────────────────────────


def scaffold_project(target_dir: Path) -> None:
    """Create ``.ai-shell.yaml`` in *target_dir* if it does not already exist."""
    _write_file(
        target_dir / ".ai-shell.yaml",
        _read_template("ai-shell.yaml"),
        overwrite=False,
    )
    console.print("[bold green]Project configuration ready.[/bold green]")
