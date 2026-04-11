"""`/ai-standardize-repo --verify` implementation.

Reads local files and diffs them against what each generator from
``standardize.*`` would produce. Also shells out to ``ai-gh rulesets view``
and ``ai-gh config --status`` for live GitHub state comparison against the
rulesets/settings specs the umbrella would apply.

Exits 1 on any drift; prints ``[PASS]`` / ``[DRIFT]`` / ``[FAIL]`` per
section.
"""

from __future__ import annotations

import difflib
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from pathlib import Path

from ai_shell.standardize.detection import Detection, RepoType, detect
from ai_shell.standardize.pipeline import _TEMPLATE_NAMES as _PIPELINE_TEMPLATES


class VerifyStatus(StrEnum):
    PASS = "PASS"
    DRIFT = "DRIFT"
    FAIL = "FAIL"


@dataclass(frozen=True)
class VerifyFinding:
    section: str
    status: VerifyStatus
    message: str
    diff: str | None = None

    def is_clean(self) -> bool:
        return self.status == VerifyStatus.PASS


def _read_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _diff(a: str, b: str, label_a: str, label_b: str) -> str:
    return "".join(
        difflib.unified_diff(
            a.splitlines(keepends=True),
            b.splitlines(keepends=True),
            fromfile=label_a,
            tofile=label_b,
            n=1,
        )
    )


def _verify_pipeline(root: Path, detection: Detection) -> VerifyFinding:
    """Compare .github/workflows/pipeline.yaml against the canonical template."""
    key = (detection.language, detection.repo_type)
    template_name = _PIPELINE_TEMPLATES.get(key)
    if template_name is None:
        return VerifyFinding(
            section="pipeline",
            status=VerifyStatus.FAIL,
            message=f"no template for {detection.language.value}/{detection.repo_type.value}",
        )
    ref = resources.files("ai_shell.templates").joinpath(
        "claude", "skills", "ai-standardize-pipeline", template_name
    )
    expected = ref.read_text(encoding="utf-8")
    actual_path = root / ".github" / "workflows" / "pipeline.yaml"
    actual = _read_or_empty(actual_path)
    if actual == expected:
        return VerifyFinding(
            section="pipeline",
            status=VerifyStatus.PASS,
            message=f"matches {template_name}",
        )
    if not actual:
        return VerifyFinding(
            section="pipeline",
            status=VerifyStatus.FAIL,
            message=f"{actual_path} missing",
        )
    return VerifyFinding(
        section="pipeline",
        status=VerifyStatus.DRIFT,
        message=f"{actual_path} differs from {template_name}",
        diff=_diff(expected, actual, f"expected/{template_name}", str(actual_path)),
    )


def _verify_renovate(root: Path, detection: Detection) -> VerifyFinding:
    from ai_shell.standardize import renovate as rv

    expected_template = (
        rv._IAC_TEMPLATE if detection.repo_type == RepoType.IAC else rv._LIBRARY_TEMPLATE
    )
    result = rv.apply(detection, root, dry_run=True)
    # We need the rendered content; re-render manually.
    rendered = rv._load_template(expected_template)
    if detection.language.value == "node":
        rendered, _ = rv._substitute_for_node(rendered)
        if detection.repo_type == RepoType.IAC:
            rendered = rv._enforce_node_iac_automerge_strategy(rendered)
    actual = _read_or_empty(result.path)
    if actual == rendered:
        return VerifyFinding(
            section="renovate", status=VerifyStatus.PASS, message="matches template"
        )
    if not actual:
        return VerifyFinding(
            section="renovate",
            status=VerifyStatus.FAIL,
            message=f"{result.path} missing",
        )
    return VerifyFinding(
        section="renovate",
        status=VerifyStatus.DRIFT,
        message=f"{result.path} differs from template",
        diff=_diff(rendered, actual, "expected", str(result.path)),
    )


def _verify_precommit(root: Path, detection: Detection) -> VerifyFinding:
    from ai_shell.standardize import precommit as pc

    if detection.language.value == "python":
        expected = pc._load_repo_template(pc._PY_TEMPLATE_NAME)
        actual_path = root / pc._PY_CONFIG
        actual = _read_or_empty(actual_path)
        if actual == expected:
            return VerifyFinding(
                section="precommit",
                status=VerifyStatus.PASS,
                message="python config matches template",
            )
        if not actual:
            return VerifyFinding(
                section="precommit",
                status=VerifyStatus.FAIL,
                message=f"{actual_path} missing",
            )
        return VerifyFinding(
            section="precommit",
            status=VerifyStatus.DRIFT,
            message=f"{actual_path} differs",
            diff=_diff(expected, actual, "expected", str(actual_path)),
        )

    if detection.language.value == "node":
        hook_expected = pc._load_precommit_template(pc._HUSKY_TEMPLATE_NAME)
        hook_actual = _read_or_empty(root / pc._HUSKY_HOOK)
        if hook_actual != hook_expected:
            return VerifyFinding(
                section="precommit",
                status=VerifyStatus.DRIFT,
                message=".husky/pre-commit differs",
            )
        lint_expected = pc._load_precommit_template(pc._LINT_STAGED_TEMPLATE_NAME)
        lint_actual = _read_or_empty(root / pc._LINT_STAGED)
        if lint_actual != lint_expected:
            return VerifyFinding(
                section="precommit",
                status=VerifyStatus.DRIFT,
                message="lint-staged.config.json differs",
            )
        return VerifyFinding(
            section="precommit",
            status=VerifyStatus.PASS,
            message="node pre-commit matches templates",
        )

    return VerifyFinding(
        section="precommit",
        status=VerifyStatus.FAIL,
        message=f"no template for language={detection.language.value}",
    )


def _verify_rulesets(root: Path, detection: Detection) -> VerifyFinding:
    """Call `ai-gh rulesets view` and diff the live set against the spec."""
    from ai_shell.standardize import rulesets as rs

    specs = rs.generate(detection)
    expected_names = {spec.name for spec in specs}
    try:
        out = subprocess.run(
            ["ai-gh", "rulesets", "view", "--json"],
            capture_output=True,
            text=True,
            cwd=root,
            check=False,
        )
    except FileNotFoundError:
        return VerifyFinding(
            section="rulesets",
            status=VerifyStatus.FAIL,
            message="ai-gh not installed",
        )
    if out.returncode != 0:
        return VerifyFinding(
            section="rulesets",
            status=VerifyStatus.FAIL,
            message=f"ai-gh rulesets view failed: {out.stderr.strip()}",
        )
    import json as _json

    try:
        live = _json.loads(out.stdout or "[]")
    except _json.JSONDecodeError:
        return VerifyFinding(
            section="rulesets",
            status=VerifyStatus.FAIL,
            message="ai-gh rulesets view emitted invalid JSON",
        )
    live_names = {item.get("name") for item in live if isinstance(item, dict)}
    missing = expected_names - live_names
    extra = live_names - expected_names
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing on GitHub: {', '.join(sorted(missing))}")
        if extra:
            parts.append(f"unexpected on GitHub: {', '.join(sorted(x for x in extra if x))}")
        return VerifyFinding(
            section="rulesets",
            status=VerifyStatus.DRIFT,
            message="; ".join(parts),
        )
    return VerifyFinding(
        section="rulesets",
        status=VerifyStatus.PASS,
        message=f"{len(live_names)} ruleset(s) present",
    )


def _verify_repo_settings(root: Path) -> VerifyFinding:
    """Call `ai-gh config --status` and look for drift flags."""
    try:
        out = subprocess.run(
            ["ai-gh", "config", "--status", "--json"],
            capture_output=True,
            text=True,
            cwd=root,
            check=False,
        )
    except FileNotFoundError:
        return VerifyFinding(
            section="repo_settings",
            status=VerifyStatus.FAIL,
            message="ai-gh not installed",
        )
    if out.returncode != 0:
        return VerifyFinding(
            section="repo_settings",
            status=VerifyStatus.DRIFT,
            message=f"ai-gh config reported drift: {out.stderr.strip() or out.stdout.strip()}",
        )
    return VerifyFinding(
        section="repo_settings",
        status=VerifyStatus.PASS,
        message="settings match one-page contract",
    )


def run(root: Path | str = ".") -> tuple[VerifyFinding, ...]:
    """Run the full verify suite against *root*."""
    root_path = Path(root).resolve()
    detection = detect(root_path)
    findings: list[VerifyFinding] = [
        VerifyFinding(
            section="detect",
            status=VerifyStatus.PASS,
            message=f"{detection.language.value}/{detection.repo_type.value}",
        ),
        _verify_pipeline(root_path, detection),
        _verify_precommit(root_path, detection),
        _verify_renovate(root_path, detection),
        _verify_rulesets(root_path, detection),
        _verify_repo_settings(root_path),
    ]
    return tuple(findings)
