"""The 10-step `/ai-standardize-repo --all` orchestrator.

Sub-skills generate content; ai-gh is called only for GitHub state mutation.

1. **Detect** repo type x language (detection.detect)
2. **Dotfiles** -- write .editorconfig and .gitignore
3. **Pre-commit** -- precommit.apply
4. **Pipeline** -- pipeline.apply (writes promote-dev-to-main.nightly.yml for iac)
5. **Renovate** -- renovate.apply
6. **Release** -- release.apply
7. **OIDC** -- shell out to ai-setup-oidc (prose-driven skill)
8. **Repo settings** -- ``ai-gh config --standardize``
9. **Rulesets** -- rulesets.generate + ``ai-gh rulesets apply <spec>``
10. **Verify** -- verify.run
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from pathlib import Path

from ai_shell.standardize import pipeline, precommit, release, renovate, rulesets, verify
from ai_shell.standardize.detection import Detection, detect


class StepStatus(StrEnum):
    OK = "OK"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class StepResult:
    step: str
    status: StepStatus
    message: str


def _write_dotfiles(root: Path) -> StepResult:
    try:
        ref = resources.files("ai_shell.templates").joinpath(
            "claude", "skills", "ai-standardize-repo", "editorconfig-template"
        )
        (root / ".editorconfig").write_text(ref.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return StepResult("dotfiles", StepStatus.FAILED, str(exc))
    return StepResult("dotfiles", StepStatus.OK, ".editorconfig written")


def _run_ai_setup_oidc(root: Path) -> StepResult:
    """Best-effort call to ai-setup-oidc skill via the external CLI.

    The skill is prose-driven; the umbrella only surfaces the step. If the
    skill is not directly callable as a CLI (today it's a Claude skill),
    this step emits a hint so the user can invoke it manually.
    """
    # The skill isn't a CLI command; surface the hint. Phase 2 can wire this
    # to `ai-gh oidc apply` or similar once that API exists.
    return StepResult(
        "oidc",
        StepStatus.SKIPPED,
        "invoke /ai-setup-oidc skill manually (no CLI entry point yet)",
    )


def _run_gh(args: list[str], cwd: Path) -> tuple[int, str, str]:
    if shutil.which("ai-gh") is None:
        return (127, "", "ai-gh not installed")
    proc = subprocess.run(["ai-gh", *args], capture_output=True, text=True, cwd=cwd, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def _run_repo_settings(root: Path) -> StepResult:
    rc, _out, err = _run_gh(["config", "--standardize"], cwd=root)
    if rc != 0:
        return StepResult(
            "repo_settings", StepStatus.FAILED, err.strip() or "ai-gh config --standardize failed"
        )
    return StepResult("repo_settings", StepStatus.OK, "ai-gh config --standardize applied")


def _run_rulesets(detection: Detection, root: Path) -> StepResult:
    specs = rulesets.generate(detection)
    applied: list[str] = []
    for spec in specs:
        rc, _out, err = _run_gh(["rulesets", "apply", str(spec.temp_path)], cwd=root)
        if rc != 0:
            return StepResult(
                "rulesets",
                StepStatus.FAILED,
                f"apply {spec.name} failed: {err.strip() or 'unknown error'}",
            )
        applied.append(spec.name)
    return StepResult("rulesets", StepStatus.OK, f"applied: {', '.join(applied)}")


def run_all(root: Path | str = ".") -> tuple[StepResult, ...]:
    """Execute the full 10-step sequence; return per-step results."""
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
    results.append(_write_dotfiles(root_path))

    # 3. Pre-commit
    try:
        pc_result = precommit.apply(detection, root_path)
        results.append(
            StepResult("precommit", StepStatus.OK, f"wrote {len(pc_result.files)} file(s)")
        )
    except Exception as exc:  # noqa: BLE001
        results.append(StepResult("precommit", StepStatus.FAILED, str(exc)))
        return tuple(results)

    # 4. Pipeline -- AI-mediated under T5-7. The Python umbrella runs the
    # read-only validator and surfaces a SKIPPED hint instructing the
    # caller to invoke `/ai-standardize-pipeline` for the merge. We do not
    # write `pipeline.yaml` from Python.
    try:
        report = pipeline.validate(root_path)
        if report.is_clean():
            results.append(
                StepResult(
                    "pipeline",
                    StepStatus.OK,
                    f"{len(report.present)} canonical gate(s) present; spec clean",
                )
            )
        else:
            summary = []
            if report.missing:
                summary.append(f"missing: {', '.join(report.missing)}")
            if report.legacy_candidates:
                summary.append(
                    "legacy: " + ", ".join(f"{n}->{g}" for _i, n, g in report.legacy_candidates)
                )
            if report.spec_failures:
                summary.append("spec: " + "; ".join(f"{g}: {r}" for g, r in report.spec_failures))
            if not report.pipeline_present:
                summary.append("pipeline.yaml missing")
            results.append(
                StepResult(
                    "pipeline",
                    StepStatus.SKIPPED,
                    "drift detected -- run `/ai-standardize-pipeline` skill: "
                    + ("; ".join(summary) or "see validate report"),
                )
            )
    except Exception as exc:  # noqa: BLE001
        results.append(StepResult("pipeline", StepStatus.FAILED, str(exc)))
        return tuple(results)

    # 5. Renovate
    try:
        rv_result = renovate.apply(detection, root_path)
        results.append(StepResult("renovate", StepStatus.OK, f"{rv_result.template}"))
    except Exception as exc:  # noqa: BLE001
        results.append(StepResult("renovate", StepStatus.FAILED, str(exc)))
        return tuple(results)

    # 6. Release
    try:
        rel_result = release.apply(detection, root_path)
        results.append(StepResult("release", StepStatus.OK, f"{rel_result.template}"))
    except Exception as exc:  # noqa: BLE001
        results.append(StepResult("release", StepStatus.FAILED, str(exc)))
        return tuple(results)

    # 7. OIDC
    results.append(_run_ai_setup_oidc(root_path))

    # 8. Repo settings
    results.append(_run_repo_settings(root_path))

    # 9. Rulesets
    results.append(_run_rulesets(detection, root_path))

    # 10. Verify
    findings = verify.run(root_path)
    drift_count = sum(1 for f in findings if not f.is_clean())
    if drift_count == 0:
        results.append(StepResult("verify", StepStatus.OK, "all sections clean"))
    else:
        results.append(
            StepResult(
                "verify",
                StepStatus.FAILED,
                f"{drift_count} section(s) drifted -- run --verify for details",
            )
        )

    return tuple(results)
