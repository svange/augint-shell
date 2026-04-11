"""The 10-step `/ai-standardize-repo --all` orchestrator.

Sub-skills generate content; ai-gh is called only for GitHub state mutation.

1. **Detect** repo type x language (detection.detect)
2. **Dotfiles** -- write .editorconfig and .gitignore
3. **Pre-commit** -- precommit.apply
4. **Pipeline** -- read-only validate; AI-mediated merge runs as a sub-skill
5. **Renovate** -- renovate.apply
6. **Release** -- release.apply
7. **OIDC** -- ai-setup-oidc skill sub-invocation (returns NEEDS_ACTION from
   Python so non-AI callers know to intervene)
8. **Repo settings** -- ``ai-gh config --standardize``
9. **Rulesets** -- rulesets.generate + ``ai-gh rulesets apply <spec>``
10. **Verify** -- verify.run

The umbrella supports a ``dry_run`` mode (T5-14) that computes every
would-be change without writing to disk or mutating GitHub state. Every
sub-generator in ``standardize.*`` already supports a ``dry_run`` kwarg;
the umbrella propagates it and chains ``--dry-run`` through to ai-gh.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ai_shell.standardize import (
    dotfiles,
    pipeline,
    precommit,
    release,
    renovate,
    rulesets,
    verify,
)
from ai_shell.standardize.detection import Detection, detect


class StepStatus(StrEnum):
    """Outcome of a single umbrella step.

    ``NEEDS_ACTION`` is distinct from ``SKIPPED``: the step could not be
    completed deterministically from Python and requires an AI sub-skill
    (or a human) to finish. The umbrella still proceeds to subsequent
    steps, but the final report surfaces NEEDS_ACTION entries as warnings
    so the caller knows to follow up.
    """

    OK = "OK"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    NEEDS_ACTION = "NEEDS_ACTION"


@dataclass(frozen=True)
class StepResult:
    step: str
    status: StepStatus
    message: str
    diff: str | None = None
    """Optional diff / plan text shown to the user in dry-run mode."""


def _write_dotfiles(root: Path, *, dry_run: bool = False) -> StepResult:
    """Delegate to ``standardize.dotfiles.apply`` (T8-2).

    The umbrella used to inline a partial editorconfig-only write; now
    both ``.editorconfig`` and ``.gitignore`` flow through the shared
    generator so ``ai-shell standardize dotfiles`` and the umbrella
    stay in lockstep.
    """
    try:
        result = dotfiles.apply(root, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001
        return StepResult("dotfiles", StepStatus.FAILED, str(exc))

    parts: list[str] = []
    diff_parts: list[str] = []
    verb = "would write" if dry_run else "wrote"
    if result.editorconfig_written:
        parts.append(".editorconfig")
        diff_parts.append(f"{verb} {result.editorconfig_path}")
    if result.gitignore_written:
        parts.append(f".gitignore (+{result.gitignore_lines_added} canonical entries)")
        diff_parts.append(
            f"{verb} {result.gitignore_path} (+{result.gitignore_lines_added} canonical entries)"
        )

    if not parts:
        return StepResult("dotfiles", StepStatus.OK, "already match canonical (no change)")

    message = f"{verb}: " + ", ".join(parts)
    diff = "; ".join(diff_parts) if diff_parts else None
    return StepResult("dotfiles", StepStatus.OK, message, diff=diff)


def _run_ai_setup_oidc(root: Path, *, dry_run: bool = False) -> StepResult:
    """Surface OIDC as a NEEDS_ACTION step, not a silent skip (T5-12).

    The Python umbrella never touches AWS IAM trust policies. The
    /ai-setup-oidc skill handles reasoning about current state and
    asking the user before changes. This function returns
    ``NEEDS_ACTION`` so the umbrella's final report shows the step as a
    yellow warning rather than a silent pass, and so non-AI callers (e.g.
    ``ai-tools workspace standardize --apply`` in a future round) know
    to run the sub-skill separately.
    """
    message = (
        "OIDC trust setup is not auto-configured by the Python umbrella. "
        "Invoke `/ai-setup-oidc` as a sub-skill to check and configure "
        "(or, if already correct, confirm via `ai-gh oidc view`)."
    )
    if dry_run:
        message = (
            "[dry-run] OIDC step would delegate to `/ai-setup-oidc` "
            "sub-skill. Python performs no AWS IAM changes regardless."
        )
    return StepResult("oidc", StepStatus.NEEDS_ACTION, message)


def _run_gh(args: list[str], cwd: Path) -> tuple[int, str, str]:
    if shutil.which("ai-gh") is None:
        return (127, "", "ai-gh not installed")
    proc = subprocess.run(["ai-gh", *args], capture_output=True, text=True, cwd=cwd, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def _run_repo_settings(root: Path, *, dry_run: bool = False) -> StepResult:
    args = ["config", "--standardize"]
    if dry_run:
        args.append("--dry-run")
    rc, out, err = _run_gh(args, cwd=root)
    if rc != 0:
        return StepResult(
            "repo_settings",
            StepStatus.FAILED,
            err.strip() or "ai-gh config --standardize failed",
        )
    if dry_run:
        return StepResult(
            "repo_settings",
            StepStatus.OK,
            "would apply canonical settings via ai-gh config --standardize",
            diff=out.strip() or None,
        )
    return StepResult("repo_settings", StepStatus.OK, "ai-gh config --standardize applied")


def _run_rulesets(detection: Detection, root: Path, *, dry_run: bool = False) -> StepResult:
    specs = rulesets.generate(detection)
    applied: list[str] = []
    diff_lines: list[str] = []
    for spec in specs:
        args = ["rulesets", "apply", str(spec.temp_path)]
        if dry_run:
            args.append("--dry-run")
        rc, out, err = _run_gh(args, cwd=root)
        if rc != 0:
            return StepResult(
                "rulesets",
                StepStatus.FAILED,
                f"apply {spec.name} failed: {err.strip() or 'unknown error'}",
            )
        applied.append(spec.name)
        if dry_run and out.strip():
            diff_lines.append(f"[{spec.name}] {out.strip()}")

    if dry_run:
        return StepResult(
            "rulesets",
            StepStatus.OK,
            f"would apply {len(applied)} ruleset(s): {', '.join(applied)}",
            diff="\n".join(diff_lines) if diff_lines else None,
        )
    return StepResult("rulesets", StepStatus.OK, f"applied: {', '.join(applied)}")


def _pipeline_step(root: Path) -> StepResult:
    """Run the read-only pipeline validator and translate to a StepResult.

    Pipeline standardization is AI-mediated (T5-7); Python never writes
    pipeline.yaml. This step only reports current drift state. The
    umbrella SKILL.md step 4 invokes /ai-standardize-pipeline as a
    sub-skill to actually perform the merge.
    """
    try:
        report = pipeline.validate(root)
    except Exception as exc:  # noqa: BLE001
        return StepResult("pipeline", StepStatus.FAILED, str(exc))

    if report.is_clean():
        return StepResult(
            "pipeline",
            StepStatus.OK,
            f"{len(report.present)} canonical gate(s) present; spec clean",
        )

    summary: list[str] = []
    if report.missing:
        summary.append(f"missing: {', '.join(report.missing)}")
    if report.legacy_candidates:
        summary.append("legacy: " + ", ".join(f"{n}->{g}" for _i, n, g in report.legacy_candidates))
    if report.spec_failures:
        summary.append("spec: " + "; ".join(f"{g}: {r}" for g, r in report.spec_failures))
    if not report.pipeline_present:
        summary.append("pipeline.yaml missing")
    return StepResult(
        "pipeline",
        StepStatus.NEEDS_ACTION,
        "drift detected -- run `/ai-standardize-pipeline` skill: "
        + ("; ".join(summary) or "see validate report"),
    )


def run_all(
    root: Path | str = ".",
    *,
    dry_run: bool = False,
) -> tuple[StepResult, ...]:
    """Execute the full 10-step sequence; return per-step results.

    When ``dry_run`` is ``True``, every step runs in compute-but-don't-write
    mode. Python generators are invoked with ``dry_run=True``; ai-gh calls
    append ``--dry-run``. No files are written to disk; no GitHub state
    is mutated. The AI-mediated pipeline step still reports drift (its
    read-only validator is unchanged), and the umbrella SKILL.md's step 4
    sub-skill invocation handles the AskUserQuestion interaction loop at
    the skill layer regardless of dry_run (see T5-14 acceptance).
    """
    root_path = Path(root).resolve()
    results: list[StepResult] = []

    # 1. Detect
    detection = detect(root_path)
    if detection.is_ambiguous():
        results.append(
            StepResult(
                "detect",
                StepStatus.FAILED,
                f"ambiguous language ({', '.join(detection.language_evidence)}) "
                "-- set [standardize] language in ai-shell.toml and retry",
            )
        )
        return tuple(results)
    results.append(
        StepResult(
            "detect",
            StepStatus.OK,
            f"{detection.language.value}/{detection.repo_type.value}",
        )
    )

    # 2. Dotfiles
    results.append(_write_dotfiles(root_path, dry_run=dry_run))

    # 3. Pre-commit
    try:
        pc_result = precommit.apply(detection, root_path, dry_run=dry_run)
        verb = "would write" if dry_run else "wrote"
        results.append(
            StepResult(
                "precommit",
                StepStatus.OK,
                f"{verb} {len(pc_result.files)} file(s)",
            )
        )
    except Exception as exc:  # noqa: BLE001
        results.append(StepResult("precommit", StepStatus.FAILED, str(exc)))
        return tuple(results)

    # 4. Pipeline -- read-only validate; merge is AI-mediated.
    results.append(_pipeline_step(root_path))

    # 5. Renovate
    try:
        rv_result = renovate.apply(detection, root_path, dry_run=dry_run)
        verb = "would render" if dry_run else "rendered"
        results.append(StepResult("renovate", StepStatus.OK, f"{verb} {rv_result.template}"))
    except Exception as exc:  # noqa: BLE001
        results.append(StepResult("renovate", StepStatus.FAILED, str(exc)))
        return tuple(results)

    # 6. Release
    try:
        rel_result = release.apply(detection, root_path, dry_run=dry_run)
        verb = "would render" if dry_run else "rendered"
        results.append(StepResult("release", StepStatus.OK, f"{verb} {rel_result.template}"))
    except Exception as exc:  # noqa: BLE001
        results.append(StepResult("release", StepStatus.FAILED, str(exc)))
        return tuple(results)

    # 7. OIDC
    results.append(_run_ai_setup_oidc(root_path, dry_run=dry_run))

    # 8. Repo settings
    results.append(_run_repo_settings(root_path, dry_run=dry_run))

    # 9. Rulesets
    results.append(_run_rulesets(detection, root_path, dry_run=dry_run))

    # 10. Verify
    findings = verify.run(root_path)
    drift_count = sum(1 for f in findings if not f.is_clean())
    if drift_count == 0:
        results.append(StepResult("verify", StepStatus.OK, "all sections clean"))
    else:
        verify_status = StepStatus.OK if dry_run else StepStatus.FAILED
        results.append(
            StepResult(
                "verify",
                verify_status,
                f"{drift_count} section(s) drifted"
                + (
                    " (dry-run: this is the pre-apply baseline, not the post-apply state)"
                    if dry_run
                    else " -- run --verify for details"
                ),
            )
        )

    return tuple(results)
