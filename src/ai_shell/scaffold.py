"""Project scaffolding for ai-shell init and tool-specific setup.

Template content lives in ``ai_shell/templates/`` as plain files
(JSON, TOML, Markdown) so they can be edited directly.
"""

from __future__ import annotations

import json
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
    content = ref.read_text(encoding="utf-8")
    return content.replace("\r\n", "\n")


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
_PROJECT_FILES = [".ai-shell.yaml", ".ai-shell.yml", ".ai-shell.toml", "ai-shell.toml"]


def _deep_merge_settings(existing: dict, template: dict) -> dict:
    """Deep-merge *template* into *existing*, preserving user customizations.

    - Dict values: recurse
    - List values: append entries from *template* not already present
    - Scalars: keep *existing* value
    - Keys only in *template*: add them
    """
    result = dict(existing)
    for key, template_value in template.items():
        if key not in result:
            result[key] = template_value
        elif isinstance(result[key], dict) and isinstance(template_value, dict):
            result[key] = _deep_merge_settings(result[key], template_value)
        elif isinstance(result[key], list) and isinstance(template_value, list):
            existing_set = set(result[key])
            new_entries = [e for e in template_value if e not in existing_set]
            result[key] = result[key] + new_entries
        # else: keep existing scalar value
    return result


def _merge_json_file(path: Path, template_content: str) -> bool:
    """Merge template JSON into an existing file, preserving user customizations.

    If the file does not exist, writes the template as-is.
    Returns ``True`` if the file was written/merged, ``False`` if skipped.
    """
    template = json.loads(template_content)

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template_content, encoding="utf-8", newline="\n")
        console.print(f"[green]Created: {path}[/green]")
        return True

    existing = json.loads(path.read_text(encoding="utf-8"))
    merged = _deep_merge_settings(existing, template)
    path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8", newline="\n")
    console.print(f"[green]Merged: {path}[/green]")
    return True


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


def scaffold_claude(
    target_dir: Path,
    *,
    overwrite: bool = False,
    clean: bool = False,
    merge: bool = False,
) -> None:
    """Create ``.claude/`` directory with settings.

    Skills are delivered via the ``augint-workflow`` plugin from ``ai-cc-tools``
    and no longer scaffolded here.
    """
    if clean:
        _clean_paths(target_dir, _CLAUDE_DIRS, _CLAUDE_FILES)
        overwrite = True
    claude_dir = target_dir / ".claude"

    # settings.json
    settings_template = _read_template("claude", "settings.json")
    if merge:
        _merge_json_file(claude_dir / "settings.json", settings_template)
    else:
        _write_file(
            claude_dir / "settings.json",
            settings_template,
            overwrite=overwrite,
        )

    console.print("[bold green]Claude configuration ready.[/bold green]")


def scaffold_project(
    target_dir: Path,
    *,
    overwrite: bool = False,
    clean: bool = False,
    merge: bool = False,
) -> None:
    """Create ``.ai-shell.yaml`` in *target_dir*."""
    if clean:
        _clean_paths(target_dir, _PROJECT_DIRS, _PROJECT_FILES)
        overwrite = True
    effective_overwrite = overwrite or merge
    _write_file(
        target_dir / ".ai-shell.yaml",
        _read_template("ai-shell.yaml"),
        overwrite=effective_overwrite,
    )

    console.print("[bold green]Project configuration ready.[/bold green]")


def scaffold_opencode(
    target_dir: Path,
    *,
    overwrite: bool = False,
    clean: bool = False,
    merge: bool = False,
) -> None:
    """Create opencode config (``opencode.json``)."""
    if clean:
        _clean_paths(target_dir, _OPENCODE_DIRS, _OPENCODE_FILES)
        overwrite = True
    opencode_template = _read_template("opencode", "opencode.json")
    if merge:
        _merge_json_file(target_dir / "opencode.json", opencode_template)
    else:
        _write_file(
            target_dir / "opencode.json",
            opencode_template,
            overwrite=overwrite,
        )

    console.print("[bold green]opencode configuration ready.[/bold green]")


def scaffold_codex(
    target_dir: Path,
    *,
    overwrite: bool = False,
    clean: bool = False,
    merge: bool = False,
) -> None:
    """Create ``.codex/`` config."""
    if clean:
        _clean_paths(target_dir, _CODEX_DIRS, _CODEX_FILES)
        overwrite = True
    effective_overwrite = overwrite or merge
    _write_file(
        target_dir / ".codex" / "config.toml",
        _read_template("codex", "config.toml"),
        overwrite=effective_overwrite,
    )

    console.print("[bold green]Codex configuration ready.[/bold green]")


def scaffold_aider(
    target_dir: Path,
    *,
    overwrite: bool = False,
    clean: bool = False,
    merge: bool = False,
) -> None:
    """Create aider config files."""
    if clean:
        _clean_paths(target_dir, _AIDER_DIRS, _AIDER_FILES)
        overwrite = True
    effective_overwrite = overwrite or merge
    _write_file(
        target_dir / ".aider.conf.yml",
        _read_template("aider", "aider.conf.yml"),
        overwrite=effective_overwrite,
    )
    _write_file(
        target_dir / ".aiderignore",
        _read_template("aider", "aiderignore"),
        overwrite=effective_overwrite,
    )

    console.print("[bold green]Aider configuration ready.[/bold green]")
