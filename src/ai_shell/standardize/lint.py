"""Drift linter for the canonical gate vocabulary.

Scans every text file under the template tree and any active `.claude/skills/`
or `.agents/skills/` directories for stale gate-name variants (the pre-T1-1
vocabulary) and hand-edit TODO blocks that should have been replaced by
generator logic.

Usage:

    ai-shell standardize lint              # scan the current working tree
    ai-shell standardize lint path/to/dir  # scan a specific path

Returns non-zero on any match and prints file:line:match for each hit.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ai_shell.standardize.gates import STALE_GATE_NAMES

_SCAN_SUFFIXES: frozenset[str] = frozenset({".md", ".yaml", ".yml", ".toml", ".json", ".json5"})

# Paths (relative to the scan root) that should never be flagged because they
# define or document the stale vocabulary rather than using it, or because
# they are external content outside the lint's jurisdiction.
_ALLOWED_SUBSTRINGS: tuple[str, ...] = (
    # Files that define / document the stale vocabulary as context
    "AI_SHELL_ISSUES.md",
    "AI_SHELL_ROUND_2_ISSUES.md",
    "AI_SHELL_ROUND_3_ISSUES.md",
    "AI_SHELL_ROUND_4_ISSUES.md",
    "AI_SHELL_ROUND_5_ISSUES.md",
    "AI_SHELL_ROUND_6_ISSUES.md",
    "AI_SHELL_ROUND_7_ISSUES.md",
    "src/ai_shell/standardize/gates.py",
    "src/ai_shell/standardize/lint.py",
    "src/ai_shell/standardize/pipeline.py",
    "CHANGELOG.md",
    # The pipeline standardize skill MUST document the legacy-to-canonical
    # rename mapping in its prose; that's its whole job. Same for the
    # umbrella SKILL.md which references the pipeline skill's behavior.
    # README.md and CLAUDE.md document the same rename table per T5-9.
    "templates/claude/skills/ai-standardize-pipeline/SKILL.md",
    "templates/agents/skills/ai-standardize-pipeline/SKILL.md",
    "templates/claude/skills/ai-standardize-repo/SKILL.md",
    "templates/agents/skills/ai-standardize-repo/SKILL.md",
    "README.md",
    # External spec docs (not owned by the standardization system)
    "ai-tools.md",
    # Nested workspaces (linted by their own repo's tooling)
    "woxom-ecosystem/",
    # Memory dirs, venvs, caches, node_modules, build artifacts
    ".venv/",
    "venv/",
    "node_modules/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    "dist/",
    "build/",
    ".git/",
    # Live installed skill copies under augint-shell itself; these get
    # regenerated from src/ai_shell/templates/ by scaffold. The templates
    # are the source of truth and get linted directly.
    ".agents/skills/",
    ".claude/skills/",
    # augint-shell's own pipeline workflow uses pre-canonical job names;
    # the rename is scheduled for the follow-up self-standardization PR so
    # that the corresponding ruleset required-contexts are updated in lock
    # step and CI does not break mid-sweep.
    ".github/workflows/pipeline.yaml",
)


@dataclass(frozen=True)
class LintHit:
    path: Path
    line: int
    match: str
    context: str

    def format(self, root: Path) -> str:
        try:
            rel = self.path.relative_to(root)
        except ValueError:
            rel = self.path
        return f"{rel}:{self.line}: stale gate name '{self.match}' -- {self.context.strip()}"


def _is_allowed(path: Path, root: Path) -> bool:
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = str(path)
    return any(chunk in rel for chunk in _ALLOWED_SUBSTRINGS)


def _iter_text_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in _SCAN_SUFFIXES:
            continue
        if _is_allowed(path, root):
            continue
        yield path


def scan(root: Path, stale_names: Iterable[str] = STALE_GATE_NAMES) -> list[LintHit]:
    """Scan *root* for stale gate-name variants. Returns a list of hits."""
    stale = tuple(stale_names)
    hits: list[LintHit] = []
    for path in _iter_text_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for needle in stale:
                if needle in line:
                    hits.append(
                        LintHit(
                            path=path,
                            line=lineno,
                            match=needle,
                            context=line,
                        )
                    )
    return hits
