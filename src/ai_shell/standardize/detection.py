"""Repo type x language detection for the standardization generators.

Language detection:
    - `pyproject.toml` without `[tool.uv].package = false` => python
    - `package.json` => node
    - both => ambiguous (caller asks the user)

Repo type detection:
    - any of the following deploy markers => iac:
        samconfig.toml, cdk.json, *.tf, serverless.yml,
        vite.config.{ts,js,mjs,cjs} + a deploy workflow step
    - otherwise => library

Caller handles ambiguity by asking the user (via AskUserQuestion in the skill
layer) and persisting the answer to `ai-shell.toml` under `[standardize]`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - python <3.11 fallback
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]


class Language(StrEnum):
    PYTHON = "python"
    NODE = "node"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


class RepoType(StrEnum):
    LIBRARY = "library"
    IAC = "iac"


@dataclass(frozen=True)
class Detection:
    """Result of running detection on a repo root."""

    language: Language
    repo_type: RepoType
    # Evidence for each classification so callers can explain the result to
    # the user (and for debugging). These are paths relative to the root.
    language_evidence: tuple[str, ...]
    repo_type_evidence: tuple[str, ...]

    def is_ambiguous(self) -> bool:
        return self.language == Language.AMBIGUOUS


# Marker files / globs that imply an iac deploy target.
_IAC_DEPLOY_MARKERS: tuple[str, ...] = (
    "samconfig.toml",
    "template.yaml",
    "cdk.json",
    "serverless.yml",
    "serverless.yaml",
)

_VITE_CONFIG_CANDIDATES: tuple[str, ...] = (
    "vite.config.ts",
    "vite.config.js",
    "vite.config.mjs",
    "vite.config.cjs",
)


def _detect_language(root: Path) -> tuple[Language, tuple[str, ...]]:
    pyproject = root / "pyproject.toml"
    package_json = root / "package.json"

    python_signal = False
    evidence: list[str] = []

    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        uv_cfg = data.get("tool", {}).get("uv", {})
        is_package = uv_cfg.get("package", True)
        if is_package:
            python_signal = True
            evidence.append("pyproject.toml")

    node_signal = package_json.is_file()
    if node_signal:
        evidence.append("package.json")

    if python_signal and node_signal:
        return Language.AMBIGUOUS, tuple(evidence)
    if python_signal:
        return Language.PYTHON, tuple(evidence)
    if node_signal:
        return Language.NODE, tuple(evidence)
    return Language.UNKNOWN, tuple(evidence)


def _has_deploy_workflow(root: Path) -> bool:
    workflows = root / ".github" / "workflows"
    if not workflows.is_dir():
        return False
    for wf in workflows.glob("*.y*ml"):
        try:
            text = wf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lowered = text.lower()
        if any(
            marker in lowered
            for marker in (
                "aws-actions/configure-aws-credentials",
                "aws s3 sync",
                "aws s3 cp",
                "cdk deploy",
            )
        ):
            return True
    return False


def _detect_repo_type(root: Path) -> tuple[RepoType, tuple[str, ...]]:
    evidence: list[str] = []

    for marker in _IAC_DEPLOY_MARKERS:
        if (root / marker).is_file():
            evidence.append(marker)

    if any((root / "main.tf").is_file() for _ in (0,)) or list(root.glob("*.tf")):
        evidence.append("*.tf")

    if evidence:
        return RepoType.IAC, tuple(evidence)

    # Vite SPA with a deploy workflow = iac (web deploys to S3/CloudFront/etc)
    vite_found = [name for name in _VITE_CONFIG_CANDIDATES if (root / name).is_file()]
    if vite_found and _has_deploy_workflow(root):
        return RepoType.IAC, tuple(vite_found + ["deploy workflow"])

    return RepoType.LIBRARY, ()


def detect(root: Path | str = ".") -> Detection:
    """Detect the language and repo type of the repository at *root*."""
    path = Path(root).resolve()
    language, lang_evidence = _detect_language(path)
    repo_type, type_evidence = _detect_repo_type(path)
    return Detection(
        language=language,
        repo_type=repo_type,
        language_evidence=lang_evidence,
        repo_type_evidence=type_evidence,
    )
