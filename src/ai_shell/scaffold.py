"""Project scaffolding for ai-shell init and tool-specific setup.

Template content lives in ``ai_shell/templates/`` as plain files
(JSON, TOML, Markdown) so they can be edited directly.
"""

from __future__ import annotations

import json
import logging
import shutil
from enum import StrEnum
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
_PROJECT_FILES = [".ai-shell.toml", "ai-shell.toml"]

_NOTES_FILE = "INSTITUTIONAL_KNOWLEDGE.md"


def _write_skill_dir(
    skills_dir: Path,
    agent_prefix: str,
    skill_name: str,
    *,
    overwrite: bool,
) -> None:
    """Write all files from a skill template directory to the target skills directory."""
    skill_template_dir = _TEMPLATES.joinpath(agent_prefix, "skills", skill_name)
    target_skill_dir = skills_dir / skill_name
    for item in skill_template_dir.iterdir():
        if item.is_file():
            _write_file(
                target_skill_dir / item.name,
                item.read_text(encoding="utf-8").replace("\r\n", "\n"),
                overwrite=overwrite,
            )


def _write_notes(target_dir: Path, repo_type: RepoType | None = None) -> None:
    """Create the institutional knowledge file if it does not exist."""
    path = target_dir / _NOTES_FILE
    if path.exists():
        console.print(f"[yellow]Skipped (protected): {path}[/yellow]")
        return
    template_name = _NOTES_TEMPLATE.get(repo_type, "notes.md")
    path.write_text(_read_template(template_name), encoding="utf-8", newline="\n")
    console.print(f"[green]Created: {path}[/green]")


def _remove_stale_skills(skills_dir: Path, active_skills: list[str]) -> None:
    """Remove skill directories that are no longer applicable for the repo type."""
    for skill_name in ALL_KNOWN_SKILLS:
        if skill_name not in active_skills:
            path = skills_dir / skill_name
            if path.exists():
                shutil.rmtree(path)
                console.print(f"[red]Removed (not applicable): {path}[/red]")


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


# ── Repo type / branch strategy enums ─────────────────────────────


class RepoType(StrEnum):
    LIBRARY = "library"
    SERVICE = "service"
    WORKSPACE = "workspace"


class BranchStrategy(StrEnum):
    MAIN = "main"
    DEV = "dev"


# ── Skill sets ────────────────────────────────────────────────────

_UNIVERSAL_SKILLS = [
    "ai-init",
    "ai-pick-issue",
    "ai-prepare-branch",
    "ai-submit-work",
    "ai-monitor-pipeline",
    "ai-status",
    "ai-rollback",
    "ai-repo-health",
    "ai-create-cmd",
    "ai-web-dev",
    "ai-standardize-repo",
    "ai-standardize-dotfiles",
    "ai-new-project",
]

_PROMOTE_SKILLS = ["ai-promote"]
_SERVICE_SKILLS = ["ai-setup-oidc"]
_WORKSPACE_SKILLS = [
    "ai-workspace-status",
    "ai-workspace-sync",
    "ai-workspace-init",
    "ai-workspace-health",
    "ai-workspace-foreach",
    "ai-workspace-pick",
    "ai-workspace-branch",
    "ai-workspace-test",
    "ai-workspace-lint",
    "ai-workspace-submit",
    "ai-workspace-update",
]

# Skills removed in the unified standardization consolidation.
# Listed here so _remove_stale_skills() cleans them from existing repos.
_DELETED_SKILLS = [
    "ai-standardize-precommit",
    "ai-standardize-pipeline",
    "ai-standardize-renovate",
    "ai-standardize-release",
    "ai-fix-repo-standards",
]


def skills_for_config(
    repo_type: RepoType | None,
    branch_strategy: BranchStrategy | None,
) -> list[str]:
    """Return the skill list for a given repo type and branch strategy."""
    if repo_type is None:
        return list(CLAUDE_SKILL_DIRS)

    skills = list(_UNIVERSAL_SKILLS)

    if repo_type == RepoType.SERVICE:
        skills.extend(_SERVICE_SKILLS)
    if repo_type == RepoType.WORKSPACE:
        skills.extend(_WORKSPACE_SKILLS)
    if branch_strategy == BranchStrategy.DEV:
        skills.extend(_PROMOTE_SKILLS)

    return skills


# All known skill names (superset for stale-skill cleanup).
ALL_KNOWN_SKILLS = sorted(
    set(_UNIVERSAL_SKILLS + _PROMOTE_SKILLS + _SERVICE_SKILLS + _WORKSPACE_SKILLS + _DELETED_SKILLS)
)

# Institutional knowledge template mapping by repo type.
_NOTES_TEMPLATE: dict[RepoType | None, str] = {
    None: "notes.md",
    RepoType.LIBRARY: "notes-library.md",
    RepoType.SERVICE: "notes-service.md",
    RepoType.WORKSPACE: "notes-workspace.md",
}


# ── Public API ──────────────────────────────────────────────────────

CLAUDE_SKILL_DIRS = [
    "ai-init",
    "ai-pick-issue",
    "ai-prepare-branch",
    "ai-submit-work",
    "ai-monitor-pipeline",
    "ai-promote",
    "ai-create-cmd",
    "ai-repo-health",
    "ai-rollback",
    "ai-status",
    "ai-web-dev",
    "ai-standardize-repo",
    "ai-standardize-dotfiles",
    "ai-new-project",
    "ai-setup-oidc",
]


def scaffold_claude(
    target_dir: Path,
    *,
    overwrite: bool = False,
    clean: bool = False,
    merge: bool = False,
    repo_type: RepoType | None = None,
    branch_strategy: BranchStrategy | None = None,
) -> None:
    """Create ``.claude/`` directory with settings and skills."""
    if clean:
        _clean_paths(target_dir, _CLAUDE_DIRS, _CLAUDE_FILES)
        overwrite = True
    effective_overwrite = overwrite or merge
    claude_dir = target_dir / ".claude"
    skills_dir = claude_dir / "skills"

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

    # skill files
    active_skills = skills_for_config(repo_type, branch_strategy)
    for skill_name in active_skills:
        _write_skill_dir(skills_dir, "claude", skill_name, overwrite=effective_overwrite)

    # Remove skills that no longer apply (e.g. after repo type change)
    if repo_type is not None:
        _remove_stale_skills(skills_dir, active_skills)

    console.print("[bold green]Claude configuration ready.[/bold green]")


AGENTS_SKILL_DIRS = list(CLAUDE_SKILL_DIRS)  # Mirrored to .agents/skills/


def _build_toml_content(
    repo_type: RepoType | None,
    branch_strategy: BranchStrategy | None,
    dev_branch: str = "dev",
) -> str:
    """Build ai-shell.toml content, prepending [project] section if configured."""
    base = _read_template("ai-shell.toml")
    if repo_type is None:
        return base

    lines = ["[project]", f'repo_type = "{repo_type.value}"']
    if branch_strategy is not None:
        lines.append(f'branch_strategy = "{branch_strategy.value}"')
    if branch_strategy == BranchStrategy.DEV:
        lines.append(f'dev_branch = "{dev_branch}"')
    lines.append("")  # blank separator

    return "\n".join(lines) + "\n" + base


def scaffold_project(
    target_dir: Path,
    *,
    overwrite: bool = False,
    clean: bool = False,
    merge: bool = False,
    repo_type: RepoType | None = None,
    branch_strategy: BranchStrategy | None = None,
    dev_branch: str = "dev",
) -> None:
    """Create ``.ai-shell.toml`` in *target_dir*."""
    if clean:
        _clean_paths(target_dir, _PROJECT_DIRS, _PROJECT_FILES)
        overwrite = True
    effective_overwrite = overwrite or merge
    _write_file(
        target_dir / ".ai-shell.toml",
        _build_toml_content(repo_type, branch_strategy, dev_branch),
        overwrite=effective_overwrite,
    )

    _write_notes(target_dir, repo_type=repo_type)
    console.print("[bold green]Project configuration ready.[/bold green]")


def scaffold_opencode(
    target_dir: Path,
    *,
    overwrite: bool = False,
    clean: bool = False,
    merge: bool = False,
    repo_type: RepoType | None = None,
    branch_strategy: BranchStrategy | None = None,
) -> None:
    """Create opencode config, institutional knowledge, and ``.agents/skills/``."""
    if clean:
        _clean_paths(target_dir, _OPENCODE_DIRS, _OPENCODE_FILES)
        overwrite = True
    effective_overwrite = overwrite or merge
    opencode_template = _read_template("opencode", "opencode.json")
    if merge:
        _merge_json_file(target_dir / "opencode.json", opencode_template)
    else:
        _write_file(
            target_dir / "opencode.json",
            opencode_template,
            overwrite=overwrite,
        )
    active_skills = skills_for_config(repo_type, branch_strategy)
    skills_dir = target_dir / ".agents" / "skills"
    for skill_name in active_skills:
        _write_skill_dir(skills_dir, "agents", skill_name, overwrite=effective_overwrite)

    if repo_type is not None:
        _remove_stale_skills(skills_dir, active_skills)

    _write_notes(target_dir, repo_type=repo_type)
    console.print("[bold green]opencode configuration ready.[/bold green]")


def scaffold_codex(
    target_dir: Path,
    *,
    overwrite: bool = False,
    clean: bool = False,
    merge: bool = False,
    repo_type: RepoType | None = None,
    branch_strategy: BranchStrategy | None = None,
) -> None:
    """Create ``.codex/`` config, institutional knowledge, and skills."""
    if clean:
        _clean_paths(target_dir, _CODEX_DIRS, _CODEX_FILES)
        overwrite = True
    effective_overwrite = overwrite or merge
    _write_file(
        target_dir / ".codex" / "config.toml",
        _read_template("codex", "config.toml"),
        overwrite=effective_overwrite,
    )
    active_skills = skills_for_config(repo_type, branch_strategy)
    skills_dir = target_dir / ".agents" / "skills"
    for skill_name in active_skills:
        _write_skill_dir(skills_dir, "agents", skill_name, overwrite=effective_overwrite)

    if repo_type is not None:
        _remove_stale_skills(skills_dir, active_skills)

    _write_notes(target_dir, repo_type=repo_type)
    console.print("[bold green]Codex configuration ready.[/bold green]")


def scaffold_aider(
    target_dir: Path,
    *,
    overwrite: bool = False,
    clean: bool = False,
    merge: bool = False,
    repo_type: RepoType | None = None,
) -> None:
    """Create aider config and the institutional knowledge file."""
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

    _write_notes(target_dir, repo_type=repo_type)
    console.print("[bold green]Aider configuration ready.[/bold green]")
