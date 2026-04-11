"""`/ai-standardize-repo --verify` implementation.

Reads local files and diffs them against what each generator from
``standardize.*`` would produce. Reads live GitHub state (rulesets and repo
settings) directly via the GitHub REST API (PyGithub) rather than shelling
out to ``ai-gh``: the ai-gh CLI is mutation-only, its read commands are
Rich-formatted and not structured.

Exits 1 on any drift; prints ``[PASS]`` / ``[DRIFT]`` / ``[FAIL]`` per
section.
"""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from pathlib import Path
from typing import Any

from ai_shell.standardize.detection import Detection, RepoType, detect
from ai_shell.standardize.pipeline import _TEMPLATE_NAMES as _PIPELINE_TEMPLATES

# Canonical repo settings per the one-page contract. These match what
# ``ai-gh config --standardize`` writes (see augint-github 1.9.2's
# ``set_repo_settings``: merge commits only, PR_TITLE/PR_BODY, auto-merge
# on, delete branch on merge always True since dev is protected by the
# ruleset, not by this flag).
_EXPECTED_REPO_SETTINGS: dict[str, Any] = {
    "allow_merge_commit": True,
    "allow_squash_merge": False,
    "allow_rebase_merge": False,
    "allow_auto_merge": True,
    "merge_commit_title": "PR_TITLE",
    "merge_commit_message": "PR_BODY",
    "delete_branch_on_merge": True,
}


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
        expected = pc._render_python_precommit(root)
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


def _load_gh_env(root: Path) -> tuple[str, str, str] | None:
    """Load GH_REPO, GH_ACCOUNT, GH_TOKEN from *root*/.env or the environment.

    Mirrors augint-github's ``load_env_config``. Returns ``None`` if any of
    the three are missing so the caller can emit a targeted FAIL.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - runtime dep, should always exist
        load_dotenv = None  # type: ignore[assignment]

    if load_dotenv is not None:
        env_file = root / ".env"
        if env_file.is_file():
            load_dotenv(env_file, override=False)

    gh_repo = os.environ.get("GH_REPO", "")
    gh_account = os.environ.get("GH_ACCOUNT", "")
    gh_token = os.environ.get("GH_TOKEN", "")
    if not gh_repo or not gh_account or not gh_token:
        return None
    return gh_repo, gh_account, gh_token


def _open_github_repo(gh_account: str, gh_repo: str, gh_token: str) -> Any:
    """Open an authenticated PyGithub Repository.

    Tries user lookup first, falls back to org — same pattern as
    augint-github's ``get_github_repo``.
    """
    from github import Auth, Github
    from github.GithubException import UnknownObjectException

    auth = Auth.Token(gh_token)
    g = Github(auth=auth)
    try:
        return g.get_user(gh_account).get_repo(gh_repo)
    except UnknownObjectException:
        return g.get_organization(gh_account).get_repo(gh_repo)


def _read_live_rulesets(repo: Any) -> list[dict[str, Any]]:
    """Fetch every ruleset on the repo with full detail.

    The list endpoint only returns summaries; we follow each one to get the
    conditions, rules, and bypass actors. Same pattern as augint-github's
    ``get_rulesets``.
    """
    _h, summaries = repo._requester.requestJsonAndCheck("GET", f"{repo.url}/rulesets")
    out: list[dict[str, Any]] = []
    for summary in summaries:
        _h, detail = repo._requester.requestJsonAndCheck(
            "GET", f"{repo.url}/rulesets/{summary['id']}"
        )
        out.append(dict(detail))
    return out


def _required_contexts(ruleset: dict[str, Any]) -> set[str]:
    for rule in ruleset.get("rules", []) or []:
        if not isinstance(rule, dict):
            continue
        if rule.get("type") != "required_status_checks":
            continue
        params = rule.get("parameters") or {}
        checks = params.get("required_status_checks") or []
        return {check.get("context", "") for check in checks if isinstance(check, dict)}
    return set()


def _verify_rulesets(root: Path, detection: Detection) -> VerifyFinding:
    """Read live rulesets from GitHub and diff against the generated spec."""
    from ai_shell.standardize import rulesets as rs

    env = _load_gh_env(root)
    if env is None:
        return VerifyFinding(
            section="rulesets",
            status=VerifyStatus.FAIL,
            message="GH_REPO / GH_ACCOUNT / GH_TOKEN not set (checked .env and environment)",
        )
    gh_repo_name, gh_account, gh_token = env

    try:
        repo = _open_github_repo(gh_account, gh_repo_name, gh_token)
    except Exception as exc:  # noqa: BLE001
        return VerifyFinding(
            section="rulesets",
            status=VerifyStatus.FAIL,
            message=f"GitHub API error opening {gh_account}/{gh_repo_name}: {exc}",
        )

    try:
        live = _read_live_rulesets(repo)
    except Exception as exc:  # noqa: BLE001
        return VerifyFinding(
            section="rulesets",
            status=VerifyStatus.FAIL,
            message=f"failed to read rulesets: {exc}",
        )

    specs = rs.generate(detection)
    expected_by_name = {spec.name: spec for spec in specs}
    live_by_name = {item.get("name"): item for item in live if isinstance(item, dict)}

    missing = set(expected_by_name) - set(live_by_name)
    extra = {n for n in live_by_name if n not in expected_by_name and n}

    drift_details: list[str] = []
    for name, spec in expected_by_name.items():
        if name not in live_by_name:
            continue
        live_contexts = _required_contexts(live_by_name[name])
        expected_contexts = set(spec.required_contexts)
        if live_contexts == expected_contexts:
            continue
        ctx_missing = expected_contexts - live_contexts
        ctx_extra = live_contexts - expected_contexts
        parts: list[str] = []
        if ctx_missing:
            parts.append("missing contexts: " + ", ".join(sorted(ctx_missing)))
        if ctx_extra:
            parts.append("extra contexts: " + ", ".join(sorted(c for c in ctx_extra if c)))
        drift_details.append(f"{name} ({'; '.join(parts)})")

    if missing or extra or drift_details:
        msg_parts: list[str] = []
        if missing:
            msg_parts.append("missing rulesets: " + ", ".join(sorted(missing)))
        if extra:
            msg_parts.append("extra rulesets: " + ", ".join(sorted(e for e in extra if e)))
        if drift_details:
            msg_parts.append("; ".join(drift_details))
        return VerifyFinding(
            section="rulesets",
            status=VerifyStatus.DRIFT,
            message="; ".join(msg_parts),
        )

    return VerifyFinding(
        section="rulesets",
        status=VerifyStatus.PASS,
        message=f"{len(specs)} ruleset(s) match spec",
    )


def _verify_repo_settings(root: Path) -> VerifyFinding:
    """Read repo settings from GitHub and diff against the one-page contract."""
    env = _load_gh_env(root)
    if env is None:
        return VerifyFinding(
            section="repo_settings",
            status=VerifyStatus.FAIL,
            message="GH_REPO / GH_ACCOUNT / GH_TOKEN not set (checked .env and environment)",
        )
    gh_repo_name, gh_account, gh_token = env

    try:
        repo = _open_github_repo(gh_account, gh_repo_name, gh_token)
    except Exception as exc:  # noqa: BLE001
        return VerifyFinding(
            section="repo_settings",
            status=VerifyStatus.FAIL,
            message=f"GitHub API error opening {gh_account}/{gh_repo_name}: {exc}",
        )

    live: dict[str, Any] = {
        "allow_merge_commit": bool(repo.allow_merge_commit),
        "allow_squash_merge": bool(repo.allow_squash_merge),
        "allow_rebase_merge": bool(repo.allow_rebase_merge),
        "allow_auto_merge": bool(repo.allow_auto_merge),
        "merge_commit_title": repo.merge_commit_title,
        "merge_commit_message": repo.merge_commit_message,
        "delete_branch_on_merge": bool(repo.delete_branch_on_merge),
    }

    diffs = [
        f"{k}: expected={_EXPECTED_REPO_SETTINGS[k]!r} actual={live[k]!r}"
        for k in _EXPECTED_REPO_SETTINGS
        if _EXPECTED_REPO_SETTINGS[k] != live[k]
    ]
    if diffs:
        return VerifyFinding(
            section="repo_settings",
            status=VerifyStatus.DRIFT,
            message="; ".join(diffs),
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
