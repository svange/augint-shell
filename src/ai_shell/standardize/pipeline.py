"""Read-only pipeline drift validator and canonical-job reference store.

T5-7 reverted the reusable-workflow architecture from T5-5. Pipeline
standardization is now an AI-mediated, single-file in-place merge: the
``ai-standardize-pipeline`` skill drives Claude through reading the
existing ``pipeline.yaml``, comparing it against canonical job snippets,
and writing one merged file. This module is the deterministic Python layer
that supports that flow:

- :func:`validate` parses an existing ``pipeline.yaml``, classifies each
  job (canonical / legacy / custom), runs minimum-spec checks on canonical
  jobs, and returns a :class:`DriftReport`. It NEVER writes to disk.
- :func:`canonical_jobs` returns the per-language-x-type mapping of
  canonical gate name to a :class:`JobReference` (template + spec) so the
  CLI can dump the snippet body for the AI to insert.
- :data:`LEGACY_NAME_MAP` and :data:`LEGACY_PREFIX_PATTERNS` encode the
  drift mapping from pre-canonical job ``name:`` strings to canonical
  gates so the validator can suggest renames.

Single-file pipelines mean a single GitHub Actions workflow run per PR
with all gates inline as jobs in the same DAG.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Literal

import yaml

from ai_shell.standardize.detection import Language, RepoType
from ai_shell.standardize.gates import load_gates

# ── Legacy name mapping ─────────────────────────────────────────────────

# Exact-match: legacy job ``name:`` -> canonical gate name. Used by
# ``validate()`` to surface rename hints in the drift report.
LEGACY_NAME_MAP: dict[str, str] = {
    "Pre-commit checks": "Code quality",
    "Quality checks": "Code quality",
    "Pre-commit": "Code quality",
    "Lint": "Code quality",
    "Security scanning": "Security",
    "SAST scanning": "Security",
    "Security scan": "Security",
    "License compliance": "Compliance",
    "Compliance reports": "Compliance",
    "Validate SAM template": "Build validation",
    "SAM build": "Build validation",
    "CDK synth": "Build validation",
}

# Prefix / contains patterns. Each entry maps a substring (case-insensitive
# match against the job ``name:``) to a canonical gate. Multiple entries
# may suggest the same gate -- the AI is expected to disambiguate via
# AskUserQuestion or by inserting a synthetic aggregator.
LEGACY_PREFIX_PATTERNS: tuple[tuple[str, str], ...] = (
    ("integration tests", "Acceptance tests"),
    ("integration test", "Acceptance tests"),
    ("smoke tests", "Acceptance tests"),
    ("smoke test", "Acceptance tests"),
    ("e2e ", "Acceptance tests"),
    ("e2e tests", "Acceptance tests"),
    ("e2e test", "Acceptance tests"),
    ("end-to-end", "Acceptance tests"),
    ("playwright", "Acceptance tests"),
    ("cypress", "Acceptance tests"),
)


# ── Spec / template dataclasses ─────────────────────────────────────────


@dataclass(frozen=True)
class StepMatcher:
    """One required-step entry from a job spec.

    ``kind == "action"``: ``matches`` is a substring of the action repo path
    (e.g. ``actions/checkout`` matches ``actions/checkout@<sha>``).

    ``kind == "run"``: ``matches_regex`` is a Python regex applied with
    ``re.search`` and ``re.MULTILINE`` to the step's ``run:`` block.
    """

    kind: Literal["action", "run"]
    matches: str | None = None
    matches_regex: str | None = None


@dataclass(frozen=True)
class JobSpec:
    """Minimum spec for a canonical gate's job in a given language x type."""

    gate: str
    language: Language
    repo_type: RepoType
    required_steps: tuple[StepMatcher, ...]


@dataclass(frozen=True)
class JobReference:
    """A canonical gate's reference template + minimum spec.

    ``template_resource`` is an importlib.resources Traversable so the CLI
    can read the snippet body without knowing the on-disk install path.
    """

    gate: str
    template_resource: Traversable
    spec: JobSpec

    def template_text(self) -> str:
        text: str = self.template_resource.read_text(encoding="utf-8")
        return text


# ── Drift report ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class DriftReport:
    """Structured result of :func:`validate`. Read-only; never mutates state."""

    pipeline_path: Path
    pipeline_present: bool
    present: tuple[str, ...] = ()  # canonical gates found by name
    missing: tuple[str, ...] = ()  # canonical gates not found
    legacy_candidates: tuple[tuple[str, str, str], ...] = ()
    """Each entry is ``(job_id, current_name, gate_guess)``."""
    custom_jobs: tuple[str, ...] = ()  # job ids the AI must preserve
    spec_failures: tuple[tuple[str, str], ...] = ()
    """Each entry is ``(gate, reason)`` for jobs that fail their minimum spec."""

    def is_clean(self) -> bool:
        """True if the pipeline has every canonical gate, all spec checks
        pass, and no legacy candidates remain."""
        return (
            self.pipeline_present
            and not self.missing
            and not self.legacy_candidates
            and not self.spec_failures
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_path": str(self.pipeline_path),
            "pipeline_present": self.pipeline_present,
            "present": list(self.present),
            "missing": list(self.missing),
            "legacy_candidates": [
                {"job_id": jid, "current_name": cn, "gate_guess": gg}
                for jid, cn, gg in self.legacy_candidates
            ],
            "custom_jobs": list(self.custom_jobs),
            "spec_failures": [{"gate": g, "reason": r} for g, r in self.spec_failures],
            "is_clean": self.is_clean(),
        }


# ── Resource loading ────────────────────────────────────────────────────

_PIPELINE_FILE = Path(".github/workflows/pipeline.yaml")
_NIGHTLY_FILE = Path(".github/workflows/promote-dev-to-main.nightly.yml")


def _skill_root() -> Traversable:
    return resources.files("ai_shell.templates").joinpath(
        "claude", "skills", "ai-standardize-pipeline"
    )


def _gate_basename(gate: str) -> str:
    """Return ``code-quality`` for ``Code quality`` etc."""
    return gate.lower().replace(" ", "-")


def _job_template_resource(language: Language, repo_type: RepoType, gate: str) -> Traversable:
    name = f"{language.value}-{repo_type.value}-job-{_gate_basename(gate)}.yaml"
    return _skill_root().joinpath("jobs", name)


def _job_spec_resource(language: Language, repo_type: RepoType, gate: str) -> Traversable:
    name = f"{language.value}-{repo_type.value}-job-{_gate_basename(gate)}.spec.yaml"
    return _skill_root().joinpath("jobs", "specs", name)


def _load_spec(language: Language, repo_type: RepoType, gate: str) -> JobSpec:
    text = _job_spec_resource(language, repo_type, gate).read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    raw_steps = data.get("required_steps") or []
    matchers: list[StepMatcher] = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            continue
        kind = raw.get("kind")
        if kind not in ("action", "run"):
            continue
        matchers.append(
            StepMatcher(
                kind=kind,
                matches=raw.get("matches"),
                matches_regex=raw.get("matches_regex"),
            )
        )
    return JobSpec(
        gate=str(data.get("gate", gate)),
        language=language,
        repo_type=repo_type,
        required_steps=tuple(matchers),
    )


def canonical_jobs(language: Language, repo_type: RepoType) -> dict[str, JobReference]:
    """Return canonical gate name -> JobReference for the language x type."""
    gates = load_gates()
    expected = gates.pre_merge + gates.post_deploy if repo_type == RepoType.IAC else gates.pre_merge
    out: dict[str, JobReference] = {}
    for gate in expected:
        out[gate] = JobReference(
            gate=gate,
            template_resource=_job_template_resource(language, repo_type, gate),
            spec=_load_spec(language, repo_type, gate),
        )
    return out


# ── Spec matching ──────────────────────────────────────────────────────


def _step_matches(step: dict[str, Any], matcher: StepMatcher) -> bool:
    if matcher.kind == "action":
        uses = step.get("uses")
        if not isinstance(uses, str) or not matcher.matches:
            return False
        # Strip the @<ref> suffix to compare the action repo path.
        action_path = uses.split("@", 1)[0].strip()
        return matcher.matches in action_path
    if matcher.kind == "run":
        run = step.get("run")
        if not isinstance(run, str) or not matcher.matches_regex:
            return False
        # MULTILINE so `^` / `$` anchor on line boundaries; DOTALL so `.`
        # spans line continuations (a single `run:` block typically looks
        # like `uv run pytest \\\n    --cov=...` -- a single shell command
        # split across YAML lines, which our regexes need to walk).
        return bool(re.search(matcher.matches_regex, run, re.MULTILINE | re.DOTALL))
    return False


def _check_spec(job_def: dict[str, Any], spec: JobSpec) -> str | None:
    """Return None if *job_def* satisfies *spec*; else a one-line failure reason.

    The check enforces in-order presence: each required step must appear
    in the job's ``steps:`` list, and they must appear in the order the
    spec declares. The user may interleave additional steps anywhere.
    """
    raw_steps = job_def.get("steps") or []
    if not isinstance(raw_steps, list):
        return "job has no `steps:` list"
    user_steps = [s for s in raw_steps if isinstance(s, dict)]

    user_idx = 0
    for matcher in spec.required_steps:
        found = False
        while user_idx < len(user_steps):
            current = user_steps[user_idx]
            user_idx += 1
            if _step_matches(current, matcher):
                found = True
                break
        if not found:
            descriptor = matcher.matches or matcher.matches_regex or "?"
            return f"missing required {matcher.kind} step: {descriptor}"
    return None


# ── Legacy name guessing ───────────────────────────────────────────────


def _guess_legacy_gate(name: str) -> str | None:
    """Map a non-canonical job ``name:`` to a canonical gate, or None."""
    if name in LEGACY_NAME_MAP:
        return LEGACY_NAME_MAP[name]
    lowered = name.lower()
    for needle, gate in LEGACY_PREFIX_PATTERNS:
        if needle in lowered:
            return gate
    return None


# ── Public read-only validate() ────────────────────────────────────────


def validate(path: Path | str = ".") -> DriftReport:
    """Read ``<path>/.github/workflows/pipeline.yaml``; return drift report.

    *path* may be a repo root or the pipeline file itself. The returned
    :class:`DriftReport` lists which canonical gates are present (by name),
    which are missing, which jobs are legacy candidates for canonical
    gates, which jobs are user-custom (preserve verbatim), and which
    canonical jobs fail their minimum spec.

    Detection of language x type uses :func:`detection.detect`. The report
    is purely informational; this function never writes to disk.
    """
    from ai_shell.standardize.detection import detect

    p = Path(path)
    if p.is_file():
        pipeline_path = p
        repo_root = p.parents[2] if len(p.parents) >= 2 else p.parent
    else:
        repo_root = p
        pipeline_path = (p / _PIPELINE_FILE).resolve()

    if not pipeline_path.is_file():
        return DriftReport(
            pipeline_path=pipeline_path,
            pipeline_present=False,
        )

    detection = detect(repo_root)
    if detection.language in (Language.AMBIGUOUS, Language.UNKNOWN):
        # We can still parse the file, but we cannot run language-specific
        # spec checks. Return a structurally-correct report with no spec
        # work performed.
        return _parse_only_report(pipeline_path)

    gates = load_gates()
    expected = (
        gates.pre_merge + gates.post_deploy
        if detection.repo_type == RepoType.IAC
        else gates.pre_merge
    )

    text = pipeline_path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return DriftReport(
            pipeline_path=pipeline_path,
            pipeline_present=True,
        )

    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, dict):
        return DriftReport(
            pipeline_path=pipeline_path,
            pipeline_present=True,
            missing=tuple(expected),
        )

    canonical = set(expected)
    present: list[str] = []
    missing_set = set(canonical)
    legacy: list[tuple[str, str, str]] = []
    custom: list[str] = []
    spec_failures: list[tuple[str, str]] = []

    refs = canonical_jobs(detection.language, detection.repo_type)

    for job_id, job_def in jobs.items():
        if not isinstance(job_def, dict):
            continue
        name = job_def.get("name")
        name_str = str(name) if name is not None else ""

        # 1) canonical name match
        if name_str in canonical:
            present.append(name_str)
            missing_set.discard(name_str)
            ref = refs.get(name_str)
            if ref is not None:
                failure = _check_spec(job_def, ref.spec)
                if failure is not None:
                    spec_failures.append((name_str, failure))
            continue

        # 2) legacy candidate match
        guess = _guess_legacy_gate(name_str) if name_str else None
        if guess is not None and guess in canonical:
            legacy.append((str(job_id), name_str, guess))
            continue

        # 3) custom job
        custom.append(str(job_id))

    return DriftReport(
        pipeline_path=pipeline_path,
        pipeline_present=True,
        present=tuple(present),
        missing=tuple(g for g in expected if g in missing_set),
        legacy_candidates=tuple(legacy),
        custom_jobs=tuple(custom),
        spec_failures=tuple(spec_failures),
    )


def _parse_only_report(pipeline_path: Path) -> DriftReport:
    """Build a minimal report when language detection is ambiguous."""
    text = pipeline_path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return DriftReport(pipeline_path=pipeline_path, pipeline_present=True)
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, dict):
        return DriftReport(pipeline_path=pipeline_path, pipeline_present=True)
    return DriftReport(
        pipeline_path=pipeline_path,
        pipeline_present=True,
        custom_jobs=tuple(str(j) for j in jobs),
    )
