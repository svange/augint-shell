"""Pipeline generator for `.github/workflows/pipeline.yaml`.

Picks one of four templates (`{python,node}-{library,iac}.pipeline.yaml`)
from the `ai-standardize-pipeline` skill directory, writes it verbatim into
the target repo, and validates that every job's `name:` matches a canonical
gate name from `gates.json`.

The template is the source of truth for both the pipeline content and the
job names. No string substitution is performed on gate names; they are
checked for drift after write and the command aborts on mismatch.

For iac repos, the generator additionally writes
`.github/workflows/promote-dev-to-main.nightly.yml` from the bundled template
(phase E).
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from ai_shell.standardize.detection import Detection, Language, RepoType
from ai_shell.standardize.gates import Gates, load_gates

_PIPELINE_PATH = Path(".github/workflows/pipeline.yaml")
_NIGHTLY_PATH = Path(".github/workflows/promote-dev-to-main.nightly.yml")

_TEMPLATE_NAMES: dict[tuple[Language, RepoType], str] = {
    (Language.PYTHON, RepoType.LIBRARY): "python-library.pipeline.yaml",
    (Language.PYTHON, RepoType.IAC): "python-iac.pipeline.yaml",
    (Language.NODE, RepoType.LIBRARY): "node-library.pipeline.yaml",
    (Language.NODE, RepoType.IAC): "node-iac.pipeline.yaml",
}


class PipelineDriftError(RuntimeError):
    """Raised when a generated pipeline's job names drift from gates.json."""


@dataclass(frozen=True)
class PipelineResult:
    """Outcome of a generator run."""

    written: bool
    template: str
    path: Path
    nightly_path: Path | None
    job_names: tuple[str, ...]
    expected_gates: tuple[str, ...]


def _load_template(template_name: str) -> str:
    ref = resources.files("ai_shell.templates").joinpath(
        "claude", "skills", "ai-standardize-pipeline", template_name
    )
    return ref.read_text(encoding="utf-8")


def _load_nightly() -> str:
    ref = resources.files("ai_shell.templates").joinpath(
        "claude",
        "skills",
        "ai-standardize-pipeline",
        "promote-dev-to-main.nightly.yml",
    )
    return ref.read_text(encoding="utf-8")


def _parse_jobs(yaml_text: str) -> dict[str, dict[str, Any]]:
    """Parse workflow YAML and return the `jobs:` mapping.

    Returns an empty dict if the workflow has no jobs (shouldn't happen for
    our templates but keeps the caller honest).
    """
    data = yaml.safe_load(yaml_text) or {}
    jobs = data.get("jobs") or {}
    if not isinstance(jobs, dict):  # pragma: no cover - defensive
        return {}
    return {
        job_id: job_def if isinstance(job_def, dict) else {} for job_id, job_def in jobs.items()
    }


def _extract_job_names(yaml_text: str) -> tuple[str, ...]:
    """Return every top-level job `name:` value in the workflow.

    Step names (inside `jobs.<id>.steps[]`) are intentionally NOT included
    — those are free text and must not collide with the gate vocabulary.
    """
    jobs = _parse_jobs(yaml_text)
    return tuple(
        job_def["name"] for job_def in jobs.values() if isinstance(job_def.get("name"), str)
    )


def _expected_gates_for(detection: Detection, gates: Gates) -> tuple[str, ...]:
    if detection.repo_type == RepoType.IAC:
        return gates.pre_merge + gates.post_deploy
    return gates.pre_merge


def _validate_job_names(
    rendered: str,
    gates: Gates,
    detection: Detection,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return ``(job_names_found, canonical_gates_missing)``.

    Asserts two things and raises :class:`PipelineDriftError` on failure:

    1. Every canonical gate that should be in this template is present as a
       top-level job name (iac includes ``Acceptance tests``).
    2. No top-level job name is a *case-drifted* variant of a canonical
       gate (e.g. ``Code Quality`` vs ``Code quality``). Post-gate jobs
       with unrelated names (``Semantic release``, ``Publish to PyPI``) are
       fine — they are not canonical gates.
    """
    top_level = _extract_job_names(rendered)
    canonical = set(gates.all_names())
    expected = set(_expected_gates_for(detection, gates))

    present = set(top_level)
    missing = tuple(sorted(expected - present))

    drifted: list[str] = []
    canonical_lower = {g.lower(): g for g in canonical}
    for name in top_level:
        if name in canonical:
            continue
        exact = canonical_lower.get(name.lower())
        if exact is not None and exact != name:
            drifted.append(name)

    if missing or drifted:
        parts = []
        if missing:
            parts.append(f"missing canonical gates: {', '.join(missing)}")
        if drifted:
            parts.append(f"case-drifted gate names: {', '.join(drifted)}")
        raise PipelineDriftError("; ".join(parts))

    return top_level, missing


def apply(
    detection: Detection,
    root: Path | str = ".",
    *,
    dry_run: bool = False,
) -> PipelineResult:
    """Write the canonical `pipeline.yaml` for *detection* into *root*."""
    if detection.language in (Language.AMBIGUOUS, Language.UNKNOWN):
        raise ValueError(
            f"cannot render pipeline for language={detection.language}; "
            "caller must resolve ambiguity first"
        )

    key = (detection.language, detection.repo_type)
    template_name = _TEMPLATE_NAMES[key]
    rendered = _load_template(template_name)

    gates = load_gates()
    job_names, _missing = _validate_job_names(rendered, gates, detection)

    root_path = Path(root).resolve()
    pipeline_path = root_path / _PIPELINE_PATH
    nightly_path: Path | None = None

    if not dry_run:
        pipeline_path.parent.mkdir(parents=True, exist_ok=True)
        pipeline_path.write_text(rendered, encoding="utf-8", newline="\n")

    if detection.repo_type == RepoType.IAC:
        nightly_path = root_path / _NIGHTLY_PATH
        try:
            nightly_rendered = _load_nightly()
        except (FileNotFoundError, OSError):
            # Nightly template lands in phase E; tolerate its absence
            # during phase B bring-up so the pipeline generator is still
            # testable in isolation.
            nightly_rendered = None
        if not dry_run and nightly_rendered is not None:
            nightly_path.parent.mkdir(parents=True, exist_ok=True)
            nightly_path.write_text(nightly_rendered, encoding="utf-8", newline="\n")

    return PipelineResult(
        written=not dry_run,
        template=template_name,
        path=pipeline_path,
        nightly_path=nightly_path,
        job_names=job_names,
        expected_gates=_expected_gates_for(detection, gates),
    )
