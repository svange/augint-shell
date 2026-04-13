"""Renovate config generator with ecosystem substitution.

Picks the library or service base template from the `ai-standardize-repo` skill
directory, substitutes manager names and dep-type strings for the detected
language, and writes `renovate.json5` to the repo root. Cross-validates
commit prefixes against `commit-scheme.json`.

Key rules:

- node/service MUST use ``automergeStrategy: merge`` (not squash). Squash drops
  the `[skip ci]` marker semantic-release emits on the promotion merge,
  which breaks the dev->main release cycle. This is explicitly asserted in
  tests.
- Python uses `pep621` manager with `project.dependencies` /
  `project.optional-dependencies` / `dependency-groups`.
- Node uses `npm` manager with `dependencies` / `devDependencies`.
- `python-semantic-release` and `semantic-release` package-name rules are
  swapped based on language.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from ai_shell.standardize.detection import Detection, Language, RepoType
from ai_shell.standardize.gates import CommitScheme, load_commit_scheme

_RENOVATE_PATH = Path("renovate.json5")

_LIBRARY_TEMPLATE = "library-template.json5"
_SERVICE_TEMPLATE = "service-template.json5"

# Replacement rules. Each entry is (needle, replacement) applied to the
# library/service template text when the language is node. Python is the default
# (templates are written in the python idiom to minimize churn for existing
# python repos).
_PYTHON_TO_NODE_SUBS: tuple[tuple[str, str], ...] = (
    ('"pep621"', '"npm"'),
    ('"project.dependencies"', '"dependencies"'),
    ('"project.optional-dependencies", "dependency-groups"', '"devDependencies"'),
    ('"project.optional-dependencies"', '"devDependencies"'),
    ('"dependency-groups"', '"devDependencies"'),
    ('"python-semantic-release"', '"semantic-release"'),
    # Comment header updates so the written file self-documents for node
    ("for Python, npm values for Node", "for Node (manager: npm)"),
    ("pep621 (for Python)", "npm (for Node)"),
)


class RenovateAlignmentError(RuntimeError):
    """Raised when the generated Renovate config drifts from commit-scheme.json."""


@dataclass(frozen=True)
class RenovateResult:
    written: bool
    template: str
    path: Path
    substitutions_applied: int


def _load_template(name: str) -> str:
    ref = resources.files("ai_shell.standardize_data").joinpath(name)
    return ref.read_text(encoding="utf-8")


def _substitute_for_node(template_text: str) -> tuple[str, int]:
    """Apply python-to-node substitutions; return (text, count_of_changes)."""
    count = 0
    out = template_text
    for needle, replacement in _PYTHON_TO_NODE_SUBS:
        if needle in out:
            out = out.replace(needle, replacement)
            count += 1
    return out, count


def _enforce_node_service_automerge_strategy(text: str) -> str:
    """Ensure node/service renovate config forces `automergeStrategy: merge`.

    If an `automergeStrategy` key already exists we force-set it; otherwise
    we inject one alongside `platformAutomerge`.
    """
    if '"automergeStrategy":' in text:
        import re

        return re.sub(
            r'"automergeStrategy"\s*:\s*"[^"]*"',
            '"automergeStrategy": "merge"',
            text,
        )
    # Inject after `"platformAutomerge": true,`
    marker = '"platformAutomerge": true,'
    if marker not in text:
        return text
    return text.replace(
        marker,
        marker + '\n  "automergeStrategy": "merge",',
    )


def _cross_validate_commit_scheme(rendered: str, scheme: CommitScheme) -> None:
    """Warn-or-fail if the rendered config references commit prefixes the
    scheme does not know about.

    This check is intentionally narrow: it asserts that every prefix the
    Renovate file uses in `commitMessagePrefix` is either in `patch_triggers`
    or in `no_release`. New prefixes must be added to `commit-scheme.json`
    first — that is what keeps Renovate and semantic-release in lockstep.
    """
    import re

    known: set[str] = (
        set(scheme.major_triggers)
        | set(scheme.minor_triggers)
        | set(scheme.patch_triggers)
        | set(scheme.no_release)
    )
    unknown: list[str] = []
    for match in re.finditer(r'"commitMessagePrefix"\s*:\s*"([^"]+)"', rendered):
        prefix = match.group(1).rstrip()
        if prefix not in known:
            unknown.append(prefix)
    if unknown:
        raise RenovateAlignmentError(
            "commit prefixes in renovate.json5 missing from commit-scheme.json: "
            + ", ".join(sorted(set(unknown)))
        )


def apply(
    detection: Detection,
    root: Path | str = ".",
    *,
    dry_run: bool = False,
) -> RenovateResult:
    """Render and write `renovate.json5` for the detected combination."""
    if detection.language in (Language.AMBIGUOUS, Language.UNKNOWN):
        raise ValueError(f"cannot render renovate: language is {detection.language}")

    template_name = (
        _SERVICE_TEMPLATE if detection.repo_type == RepoType.SERVICE else _LIBRARY_TEMPLATE
    )
    rendered = _load_template(template_name)

    substitutions = 0
    if detection.language == Language.NODE:
        rendered, substitutions = _substitute_for_node(rendered)
        if detection.repo_type == RepoType.SERVICE:
            rendered = _enforce_node_service_automerge_strategy(rendered)

    scheme = load_commit_scheme()
    _cross_validate_commit_scheme(rendered, scheme)

    root_path = Path(root).resolve()
    out_path = root_path / _RENOVATE_PATH
    if not dry_run:
        out_path.write_text(rendered, encoding="utf-8", newline="\n")

    return RenovateResult(
        written=not dry_run,
        template=template_name,
        path=out_path,
        substitutions_applied=substitutions,
    )
