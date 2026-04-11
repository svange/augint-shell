"""Pre-commit hook generator.

Python path: writes `.pre-commit-config.yaml` from the bundled
`python-template.pre-commit-config.yaml` in the `ai-standardize-repo` skill
directory.

Node path: writes `.husky/pre-commit` and `lint-staged.config.json` from the
bundled templates in the `ai-standardize-precommit` skill directory, and
merges `"prepare": "husky install"` into `package.json.scripts`. Idempotent
on a second run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from ai_shell.standardize.detection import Detection, Language

_PY_CONFIG = Path(".pre-commit-config.yaml")
_HUSKY_HOOK = Path(".husky/pre-commit")
_LINT_STAGED = Path("lint-staged.config.json")
_PACKAGE_JSON = Path("package.json")

_PY_TEMPLATE_NAME = "python-template.pre-commit-config.yaml"
_HUSKY_TEMPLATE_NAME = "node-template.husky-pre-commit"
_LINT_STAGED_TEMPLATE_NAME = "node-template.lint-staged.config.json"


@dataclass(frozen=True)
class PrecommitResult:
    written: bool
    language: Language
    files: tuple[Path, ...]


def _load_repo_template(name: str) -> str:
    ref = resources.files("ai_shell.templates").joinpath(
        "claude", "skills", "ai-standardize-repo", name
    )
    return ref.read_text(encoding="utf-8")


def _load_precommit_template(name: str) -> str:
    ref = resources.files("ai_shell.templates").joinpath(
        "claude", "skills", "ai-standardize-precommit", name
    )
    return ref.read_text(encoding="utf-8")


# Substitution marker in python-template.pre-commit-config.yaml. The
# generator replaces this placeholder based on detected repo state:
#   - if a SAM ``template.yaml`` exists at the root, render the exclude line
#     so check-yaml skips SAM templates (they contain invalid-YAML intrinsic
#     functions like ``!Ref`` and ``!GetAtt``)
#   - otherwise render as an empty string so the hook has no exclude
_CHECK_YAML_EXCLUDE_MARKER = "{{CHECK_YAML_EXCLUDE}}"
_CHECK_YAML_EXCLUDE_LINE = "\n        exclude: '(^templates/.*\\.yaml$|.*template\\.yaml$)'"


def _render_python_precommit(root: Path) -> str:
    """Load the python pre-commit template and apply substitutions."""
    content = _load_repo_template(_PY_TEMPLATE_NAME)
    has_sam_template = (root / "template.yaml").is_file() or (root / "template.yml").is_file()
    substitution = _CHECK_YAML_EXCLUDE_LINE if has_sam_template else ""
    return content.replace(_CHECK_YAML_EXCLUDE_MARKER, substitution)


def _apply_python(root: Path, dry_run: bool) -> tuple[Path, ...]:
    content = _render_python_precommit(root)
    target = root / _PY_CONFIG
    if not dry_run:
        target.write_text(content, encoding="utf-8", newline="\n")
    return (target,)


def _merge_prepare_script(package_json: Path) -> bool:
    """Merge `"prepare": "husky install"` into package.json scripts.

    Returns True if the file was modified, False if nothing needed to change.
    Idempotent: if `prepare` is already set, leaves it alone.
    """
    if not package_json.is_file():
        return False
    data = json.loads(package_json.read_text(encoding="utf-8"))
    scripts = data.setdefault("scripts", {})
    if scripts.get("prepare") == "husky install":
        return False
    scripts["prepare"] = "husky install"
    data["scripts"] = scripts
    package_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    return True


def _apply_node(root: Path, dry_run: bool) -> tuple[Path, ...]:
    hook_content = _load_precommit_template(_HUSKY_TEMPLATE_NAME)
    lint_staged_content = _load_precommit_template(_LINT_STAGED_TEMPLATE_NAME)

    hook_path = root / _HUSKY_HOOK
    lint_staged_path = root / _LINT_STAGED
    package_json = root / _PACKAGE_JSON

    files = [hook_path, lint_staged_path]
    if not dry_run:
        hook_path.parent.mkdir(parents=True, exist_ok=True)
        hook_path.write_text(hook_content, encoding="utf-8", newline="\n")
        # Make the hook executable (ignored on Windows but harmless).
        try:
            hook_path.chmod(0o755)
        except OSError:
            pass
        lint_staged_path.write_text(lint_staged_content, encoding="utf-8", newline="\n")
        if _merge_prepare_script(package_json):
            files.append(package_json)

    return tuple(files)


def apply(
    detection: Detection,
    root: Path | str = ".",
    *,
    dry_run: bool = False,
) -> PrecommitResult:
    """Generate pre-commit configuration for the detected language."""
    if detection.language == Language.PYTHON:
        root_path = Path(root).resolve()
        files = _apply_python(root_path, dry_run)
        return PrecommitResult(written=not dry_run, language=Language.PYTHON, files=files)
    if detection.language == Language.NODE:
        root_path = Path(root).resolve()
        files = _apply_node(root_path, dry_run)
        return PrecommitResult(written=not dry_run, language=Language.NODE, files=files)
    raise ValueError(f"cannot generate pre-commit for language={detection.language}")
