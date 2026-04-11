"""Dotfiles generator: `.editorconfig` + `.gitignore`.

The ``.editorconfig`` path is an idempotent full-file write from the
canonical template. The ``.gitignore`` path is an append-only merge:
canonical entries that aren't already present get added under a clearly
labeled comment block, and existing user entries are never touched.

The ``/ai-standardize-dotfiles`` skill drives the user-facing
AskUserQuestion flow (detect customizations, classify, confirm before
acting). This module is the deterministic Python layer the skill calls
once the user has approved the write.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

_EDITORCONFIG = Path(".editorconfig")
_GITIGNORE = Path(".gitignore")

_EDITORCONFIG_TEMPLATE_NAME = "editorconfig-template"
_GITIGNORE_TEMPLATE_NAME = "gitignore-template"

_GITIGNORE_APPEND_MARKER = "# === Canonical entries (ai-shell standardize dotfiles) ==="


@dataclass(frozen=True)
class DotfilesResult:
    editorconfig_path: Path
    editorconfig_written: bool
    gitignore_path: Path
    gitignore_written: bool
    gitignore_lines_added: int
    files: tuple[Path, ...]


def _skill_resource(name: str) -> Traversable:
    return resources.files("ai_shell.templates").joinpath(
        "claude", "skills", "ai-standardize-dotfiles", name
    )


def _load_editorconfig() -> str:
    return _skill_resource(_EDITORCONFIG_TEMPLATE_NAME).read_text(encoding="utf-8")


def _load_gitignore() -> str:
    return _skill_resource(_GITIGNORE_TEMPLATE_NAME).read_text(encoding="utf-8")


def _existing_gitignore_entries(text: str) -> set[str]:
    """Return the set of non-blank, non-comment lines (trimmed) in *text*.

    Comment headers are ignored so we only compare actual ignore entries.
    This is deliberately loose: we treat any non-comment line as a literal
    entry and use it only for duplicate-suppression on append.
    """
    entries: set[str] = set()
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        entries.add(stripped)
    return entries


def _canonical_gitignore_missing(existing_text: str) -> list[str]:
    """Return canonical gitignore lines absent from *existing_text*.

    Preserves source order and preserves comment-header lines adjacent to
    any entry actually added (so the resulting section still reads as
    coherent groups). Pure-canonical sections whose entries are fully
    present are dropped entirely from the append so we don't add dead
    headers.
    """
    existing = _existing_gitignore_entries(existing_text)
    template = _load_gitignore()

    # Walk canonical lines grouped by header. Within each group, decide
    # whether to emit anything at all; if nothing in the group is missing,
    # drop the header to keep the append tight.
    groups: list[tuple[str | None, list[str]]] = []
    current_header: str | None = None
    current_lines: list[str] = []
    for raw in template.splitlines():
        stripped = raw.strip()
        if stripped.startswith("#") and stripped.endswith("==="):
            # New header boundary. Flush the previous group.
            if current_header is not None or current_lines:
                groups.append((current_header, current_lines))
            current_header = raw
            current_lines = []
            continue
        current_lines.append(raw)
    groups.append((current_header, current_lines))

    out: list[str] = []
    for header, lines in groups:
        missing_in_group: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                # Intra-group comment: keep alongside missing entries.
                missing_in_group.append(line)
                continue
            if stripped not in existing:
                missing_in_group.append(line)
        # Drop leading/trailing blank-ish clutter: if the group contains
        # no real entries, skip it entirely (including its header).
        has_real_entry = any(
            ln.strip() and not ln.strip().startswith("#") for ln in missing_in_group
        )
        if not has_real_entry:
            continue
        if header is not None:
            out.append(header)
        out.extend(missing_in_group)
    return out


def _merge_editorconfig(root: Path, dry_run: bool) -> tuple[Path, bool]:
    target = root / _EDITORCONFIG
    expected = _load_editorconfig()
    if target.is_file():
        actual = target.read_text(encoding="utf-8")
        if actual == expected:
            return target, False
    if dry_run:
        return target, True
    target.write_text(expected, encoding="utf-8", newline="\n")
    return target, True


def _merge_gitignore(root: Path, dry_run: bool) -> tuple[Path, bool, int]:
    target = root / _GITIGNORE
    existing_text = target.read_text(encoding="utf-8") if target.is_file() else ""
    missing_lines = _canonical_gitignore_missing(existing_text)
    if not missing_lines:
        return target, False, 0

    # Count only real entries, not comment headers, for the report.
    added_count = sum(1 for ln in missing_lines if ln.strip() and not ln.strip().startswith("#"))

    if dry_run:
        return target, True, added_count

    append_block_lines: list[str] = []
    if existing_text and not existing_text.endswith("\n"):
        append_block_lines.append("")  # force newline before marker
    if existing_text:
        append_block_lines.append("")  # visual separation
    append_block_lines.append(_GITIGNORE_APPEND_MARKER)
    append_block_lines.extend(missing_lines)
    append_block = "\n".join(append_block_lines) + "\n"

    target.write_text(existing_text + append_block, encoding="utf-8", newline="\n")
    return target, True, added_count


def apply(root: Path | str = ".", *, dry_run: bool = False) -> DotfilesResult:
    """Write the canonical ``.editorconfig`` and append canonical
    ``.gitignore`` entries.

    Idempotent on re-run: the second call detects no drift and returns a
    result with ``*_written=False`` and no files added.

    When ``dry_run=True``, the function computes would-be writes but
    touches nothing on disk. ``DotfilesResult.files`` still lists the
    paths that would change so callers can report a plan.
    """
    root_path = Path(root).resolve()

    ec_path, ec_written = _merge_editorconfig(root_path, dry_run)
    gi_path, gi_written, added = _merge_gitignore(root_path, dry_run)

    files: list[Path] = []
    if ec_written:
        files.append(ec_path)
    if gi_written:
        files.append(gi_path)

    return DotfilesResult(
        editorconfig_path=ec_path,
        editorconfig_written=ec_written,
        gitignore_path=gi_path,
        gitignore_written=gi_written,
        gitignore_lines_added=added,
        files=tuple(files),
    )
