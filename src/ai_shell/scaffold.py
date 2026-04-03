"""Project scaffolding for ai-shell init and tool-specific setup.

Template content lives in ``ai_shell/templates/`` as plain files
(JSON, TOML, Markdown) so they can be edited directly.
"""

from __future__ import annotations

import logging
import shutil
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


def _clean_paths(target_dir: Path, dirs: list[str], files: list[str]) -> None:
    """Remove directories and files managed by scaffolding."""
    for d in dirs:
        path = target_dir / d
        if path.exists():
            shutil.rmtree(path)
            console.print(f"[red]Removed: {path}[/red]")
    for f in files:
        path = target_dir / f
        if path.exists():
            path.unlink()
            console.print(f"[red]Removed: {path}[/red]")


# Managed paths per tool (directories and loose files)
_CLAUDE_DIRS = [".claude"]
_CLAUDE_FILES: list[str] = []

_OPENCODE_DIRS = [".agents"]
_OPENCODE_FILES = ["opencode.json"]

_CODEX_DIRS = [".codex", ".agents"]
_CODEX_FILES: list[str] = []

_AIDER_DIRS: list[str] = []
_AIDER_FILES = [".aider.conf.yml", ".aiderignore"]

_PROJECT_DIRS: list[str] = []
_PROJECT_FILES = ["ai-shell.toml"]

_NOTES_FILE = "NOTES.md"


def _write_notes(target_dir: Path) -> None:
    """Create NOTES.md if it does not exist. Never overwrite or delete."""
    path = target_dir / _NOTES_FILE
    if path.exists():
        console.print(f"[yellow]Skipped (protected): {path}[/yellow]")
        return
    path.write_text(_read_template("notes.md"), encoding="utf-8")
    console.print(f"[green]Created: {path}[/green]")


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

CLAUDE_SKILL_DIRS = [
    "ai-pick-issue",
    "ai-prepare-branch",
    "ai-submit-work",
    "ai-monitor-pipeline",
    "ai-promote",
    "ai-create-cmd",
    "ai-repo-health",
    "ai-web-dev",
    "ai-standardize-renovate",
    "ai-standardize-release",
    "ai-standardize-pipeline",
    "ai-standardize-precommit",
    "ai-standardize-dotfiles",
    "ai-standardize-repo",
]


def scaffold_claude(target_dir: Path, *, overwrite: bool = False, clean: bool = False) -> None:
    """Create ``.claude/`` directory with settings and skills."""
    if clean:
        _clean_paths(target_dir, _CLAUDE_DIRS, _CLAUDE_FILES)
        overwrite = True
    claude_dir = target_dir / ".claude"
    skills_dir = claude_dir / "skills"

    # settings.json
    _write_file(
        claude_dir / "settings.json",
        _read_template("claude", "settings.json"),
        overwrite=overwrite,
    )

    # skill files
    for skill_name in CLAUDE_SKILL_DIRS:
        _write_file(
            skills_dir / skill_name / "SKILL.md",
            _read_template("claude", "skills", skill_name, "SKILL.md"),
            overwrite=overwrite,
        )

    _write_notes(target_dir)
    console.print("[bold green]Claude configuration ready.[/bold green]")


AGENTS_SKILL_DIRS = list(CLAUDE_SKILL_DIRS)  # Mirrored to .agents/skills/


def scaffold_project(target_dir: Path, *, overwrite: bool = False, clean: bool = False) -> None:
    """Create ``ai-shell.toml`` in *target_dir*."""
    if clean:
        _clean_paths(target_dir, _PROJECT_DIRS, _PROJECT_FILES)
        overwrite = True
    _write_file(
        target_dir / "ai-shell.toml",
        _read_template("ai-shell.toml"),
        overwrite=overwrite,
    )

    _write_notes(target_dir)
    console.print("[bold green]Project configuration ready.[/bold green]")


def scaffold_opencode(target_dir: Path, *, overwrite: bool = False, clean: bool = False) -> None:
    """Create opencode configuration, NOTES.md, and ``.agents/skills/``."""
    if clean:
        _clean_paths(target_dir, _OPENCODE_DIRS, _OPENCODE_FILES)
        overwrite = True
    _write_file(
        target_dir / "opencode.json",
        _read_template("opencode", "opencode.json"),
        overwrite=overwrite,
    )
    for skill_name in AGENTS_SKILL_DIRS:
        _write_file(
            target_dir / ".agents" / "skills" / skill_name / "SKILL.md",
            _read_template("agents", "skills", skill_name, "SKILL.md"),
            overwrite=overwrite,
        )

    _write_notes(target_dir)
    console.print("[bold green]opencode configuration ready.[/bold green]")


def scaffold_codex(target_dir: Path, *, overwrite: bool = False, clean: bool = False) -> None:
    """Create ``.codex/`` config, NOTES.md, and ``.agents/skills/``."""
    if clean:
        _clean_paths(target_dir, _CODEX_DIRS, _CODEX_FILES)
        overwrite = True
    _write_file(
        target_dir / ".codex" / "config.toml",
        _read_template("codex", "config.toml"),
        overwrite=overwrite,
    )
    for skill_name in AGENTS_SKILL_DIRS:
        _write_file(
            target_dir / ".agents" / "skills" / skill_name / "SKILL.md",
            _read_template("agents", "skills", skill_name, "SKILL.md"),
            overwrite=overwrite,
        )

    _write_notes(target_dir)
    console.print("[bold green]Codex configuration ready.[/bold green]")


def scaffold_aider(target_dir: Path, *, overwrite: bool = False, clean: bool = False) -> None:
    """Create ``.aider.conf.yml``, ``NOTES.md``, and ``.aiderignore``."""
    if clean:
        _clean_paths(target_dir, _AIDER_DIRS, _AIDER_FILES)
        overwrite = True
    _write_file(
        target_dir / ".aider.conf.yml",
        _read_template("aider", "aider.conf.yml"),
        overwrite=overwrite,
    )
    _write_file(
        target_dir / ".aiderignore",
        _read_template("aider", "aiderignore"),
        overwrite=overwrite,
    )

    _write_notes(target_dir)
    console.print("[bold green]Aider configuration ready.[/bold green]")
