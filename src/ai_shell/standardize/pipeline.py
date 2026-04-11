"""Merge-aware pipeline generator using reusable workflow composition.

Replaces the old verbatim-overwrite model with Option A from T5-5:

- **Canonical, regenerated every run**: one reusable workflow file per gate,
  written as ``.github/workflows/_gate-<slug>.yaml``. These are the
  tool-owned contract. User edits will be overwritten on the next run.

- **User-owned after first run**: the top-level ``.github/workflows/pipeline.yaml``.
  On first run (file does not exist) the generator writes a sensible scaffold
  that wires every canonical gate via ``uses:``. On subsequent runs the
  generator **leaves pipeline.yaml alone** but parses it to assert that
  every expected canonical gate is still referenced via
  ``uses: ./.github/workflows/_gate-<slug>.yaml``. If any reference is
  missing the command aborts with a user-actionable error.

- **iac only**: additionally writes ``promote-dev-to-main.nightly.yml``.

This preserves user customizations (custom jobs, reordered dependency
graphs, wiring acceptance tests after repo-specific post-deploy stages,
etc.) while guaranteeing the canonical contract is honored.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

import yaml

from ai_shell.standardize.detection import Detection, Language, RepoType
from ai_shell.standardize.gates import Gates, load_gates

_WORKFLOWS_DIR = Path(".github/workflows")
_PIPELINE_FILE = _WORKFLOWS_DIR / "pipeline.yaml"
_NIGHTLY_FILE = _WORKFLOWS_DIR / "promote-dev-to-main.nightly.yml"

# Map canonical gate name -> slug used in the `_gate-<slug>.yaml` filename.
# Keep in lockstep with gates.json. The slug is what the user's pipeline.yaml
# references via `uses: ./.github/workflows/_gate-<slug>.yaml`.
_GATE_SLUG: dict[str, str] = {
    "Code quality": "code-quality",
    "Security": "security",
    "Unit tests": "unit-tests",
    "Compliance": "compliance",
    "Build validation": "build-validation",
    "Acceptance tests": "acceptance-tests",
}

# Gates whose implementation is identical across library/iac for a given
# language. The generator picks the language-prefixed template
# (e.g. ``python-gate-security.yaml``) without a type discriminator.
_SHARED_GATE_SLUGS: frozenset[str] = frozenset(
    {"code-quality", "security", "unit-tests", "compliance"}
)

_REUSABLE_USES_PREFIX = "./.github/workflows/_gate-"


class PipelineDriftError(RuntimeError):
    """Raised when user-owned ``pipeline.yaml`` is missing a canonical gate."""


@dataclass(frozen=True)
class PipelineResult:
    """Outcome of a generator run."""

    # True if the top-level pipeline.yaml was freshly scaffolded this run.
    # False if it already existed and was preserved.
    scaffold_written: bool
    pipeline_path: Path
    gate_files: tuple[Path, ...]
    nightly_path: Path | None
    expected_gates: tuple[str, ...]


def _template_resource(name: str) -> Traversable:
    return resources.files("ai_shell.templates").joinpath(
        "claude", "skills", "ai-standardize-pipeline", name
    )


def _load_template(name: str) -> str:
    content: str = _template_resource(name).read_text(encoding="utf-8")
    return content


def _gate_filename(canonical_name: str) -> str:
    return f"_gate-{_GATE_SLUG[canonical_name]}.yaml"


def _gate_template_name(language: Language, repo_type: RepoType, canonical_name: str) -> str:
    """Return the source template filename for a given gate + combination."""
    slug = _GATE_SLUG[canonical_name]
    if slug in _SHARED_GATE_SLUGS:
        return f"{language.value}-gate-{slug}.yaml"
    return f"{language.value}-{repo_type.value}-gate-{slug}.yaml"


def _scaffold_template_name(language: Language, repo_type: RepoType) -> str:
    return f"{language.value}-{repo_type.value}-pipeline.yaml"


def _expected_gates_for(detection: Detection, gates: Gates) -> tuple[str, ...]:
    if detection.repo_type == RepoType.IAC:
        return gates.pre_merge + gates.post_deploy
    return gates.pre_merge


def _load_nightly() -> str | None:
    try:
        return _load_template("promote-dev-to-main.nightly.yml")
    except FileNotFoundError:
        return None


# ── Validation of existing user-owned pipeline.yaml ────────────────────


def _slug_from_uses(uses: str) -> str | None:
    """Extract the gate slug from a `uses: ./.github/workflows/_gate-<slug>.yaml`
    reference, or return None if *uses* is not a canonical reference."""
    if not uses.startswith(_REUSABLE_USES_PREFIX):
        return None
    if not uses.endswith(".yaml"):
        return None
    return uses[len(_REUSABLE_USES_PREFIX) : -len(".yaml")]


def _referenced_gate_names(pipeline_yaml: dict[str, Any]) -> set[str]:
    """Walk a parsed pipeline.yaml dict and return the set of canonical gate
    names it references via `uses: ./.github/workflows/_gate-<slug>.yaml`."""
    jobs = pipeline_yaml.get("jobs") or {}
    if not isinstance(jobs, dict):
        return set()

    # Reverse slug -> canonical name lookup
    slug_to_gate = {slug: gate for gate, slug in _GATE_SLUG.items()}

    referenced: set[str] = set()
    for job_def in jobs.values():
        if not isinstance(job_def, dict):
            continue
        uses = job_def.get("uses")
        if not isinstance(uses, str):
            continue
        slug = _slug_from_uses(uses)
        if slug is None:
            continue
        gate = slug_to_gate.get(slug)
        if gate is not None:
            referenced.add(gate)
    return referenced


def _validate_existing_pipeline(
    pipeline_text: str,
    expected_gates: tuple[str, ...],
    pipeline_path: Path,
) -> None:
    """Parse the user-owned pipeline.yaml and raise if any expected canonical
    gate is not referenced via a reusable-workflow `uses:`."""
    try:
        data = yaml.safe_load(pipeline_text) or {}
    except yaml.YAMLError as exc:
        raise PipelineDriftError(f"{pipeline_path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise PipelineDriftError(f"{pipeline_path} top level must be a mapping")
    referenced = _referenced_gate_names(data)
    missing = [g for g in expected_gates if g not in referenced]
    if not missing:
        return

    hints = []
    for gate in missing:
        slug = _GATE_SLUG[gate]
        hints.append(
            f"  {slug}:\n"
            f"    name: {gate}\n"
            f"    uses: {_REUSABLE_USES_PREFIX}{slug}.yaml\n"
            f"    secrets: inherit"
        )
    raise PipelineDriftError(
        f"{pipeline_path} is missing canonical gate reference(s): "
        + ", ".join(missing)
        + ".\nRe-add the following job(s) under `jobs:`:\n"
        + "\n".join(hints)
    )


# ── Main entry point ────────────────────────────────────────────────────


def apply(
    detection: Detection,
    root: Path | str = ".",
    *,
    dry_run: bool = False,
) -> PipelineResult:
    """Write gate files and scaffold-or-validate the user-owned pipeline.yaml."""
    if detection.language in (Language.AMBIGUOUS, Language.UNKNOWN):
        raise ValueError(
            f"cannot render pipeline for language={detection.language}; "
            "caller must resolve ambiguity first"
        )

    gates = load_gates()
    expected = _expected_gates_for(detection, gates)
    root_path = Path(root).resolve()
    workflows_path = root_path / _WORKFLOWS_DIR
    pipeline_path = root_path / _PIPELINE_FILE

    # 1. Write every `_gate-<slug>.yaml` file. Always canonical, always
    #    overwritten. These are tool-owned.
    gate_files: list[Path] = []
    for gate_name in expected:
        template_name = _gate_template_name(detection.language, detection.repo_type, gate_name)
        dest_name = _gate_filename(gate_name)
        content = _load_template(template_name)
        dest = workflows_path / dest_name
        gate_files.append(dest)
        if not dry_run:
            workflows_path.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8", newline="\n")

    # 2. pipeline.yaml: scaffold if missing, validate if present.
    scaffold_written = False
    if pipeline_path.is_file():
        existing = pipeline_path.read_text(encoding="utf-8")
        _validate_existing_pipeline(existing, expected, pipeline_path)
    else:
        scaffold_content = _load_template(
            _scaffold_template_name(detection.language, detection.repo_type)
        )
        scaffold_written = True
        if not dry_run:
            workflows_path.mkdir(parents=True, exist_ok=True)
            pipeline_path.write_text(scaffold_content, encoding="utf-8", newline="\n")

    # 3. iac: nightly promotion template (tool-owned).
    nightly_path: Path | None = None
    if detection.repo_type == RepoType.IAC:
        nightly_path = root_path / _NIGHTLY_FILE
        nightly_content = _load_nightly()
        if nightly_content is not None and not dry_run:
            workflows_path.mkdir(parents=True, exist_ok=True)
            nightly_path.write_text(nightly_content, encoding="utf-8", newline="\n")

    return PipelineResult(
        scaffold_written=scaffold_written,
        pipeline_path=pipeline_path,
        gate_files=tuple(gate_files),
        nightly_path=nightly_path,
        expected_gates=expected,
    )
