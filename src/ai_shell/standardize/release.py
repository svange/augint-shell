"""Semantic-release config generator.

Four code paths, one per ``{python,node} x {library,service}`` combination:

- ``python/library``: rewrite ``[tool.semantic_release]`` in ``pyproject.toml``
  from ``python-template.toml``. Branches = ``["main"]``.
- ``python/service``: same template, branches = ``["main", "dev"]``.
- ``node/library``: write ``.releaserc.json`` from ``node-template.releaserc.json``
  with plugins including ``@semantic-release/npm`` (publishes to npm).
- ``node/service``: write ``.releaserc.json`` with plugins MINUS
  ``@semantic-release/npm`` (deploys, doesn't publish).

All variants cross-validate against ``commit-scheme.json`` to keep Renovate
prefixes and semantic-release exclude patterns aligned.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import tomlkit

from ai_shell.standardize.detection import Detection, Language, RepoType
from ai_shell.standardize.gates import CommitScheme, load_commit_scheme

_PYTHON_TEMPLATE = "python-template.toml"
_NODE_TEMPLATE = "node-template.releaserc.json"
_PYPROJECT = Path("pyproject.toml")
_RELEASERC = Path(".releaserc.json")


class ReleaseAlignmentError(RuntimeError):
    """Raised when the generated release config drifts from commit-scheme.json."""


@dataclass(frozen=True)
class ReleaseResult:
    written: bool
    template: str
    path: Path
    plugins: tuple[str, ...]


def _load_repo_template(name: str) -> str:
    ref = resources.files("ai_shell.standardize_data").joinpath(name)
    return ref.read_text(encoding="utf-8")


def _render_python_semantic_release_block(
    template_text: str,
    *,
    branches: tuple[str, ...],
    project_name: str,
    package_name: str,
) -> tomlkit.TOMLDocument:
    """Render the python-template.toml substitutions into a TOMLDocument.

    The template contains `{project-name}` and `{package_name}` placeholders
    plus the `[tool.semantic_release.branches.main]` section that service needs
    extended for the `dev` branch.
    """
    # Simple placeholder substitution BEFORE parsing, because tomlkit will
    # rewrite the string values on assign and we want the whole section
    # fully canonical.
    rendered = template_text.replace("{project-name}", project_name).replace(
        "{package_name}", package_name
    )
    doc = tomlkit.parse(rendered)

    if "dev" in branches:
        # python-semantic-release has no "dev" prerelease config in the base
        # template. Add [tool.semantic_release.branches.dev] matching dev as
        # a non-prerelease so service repos version on both branches.
        tool = doc.setdefault("tool", tomlkit.table())
        sr = tool.setdefault("semantic_release", tomlkit.table())
        branches_tbl = sr.setdefault("branches", tomlkit.table())
        dev = tomlkit.table()
        dev["match"] = "dev"
        dev["prerelease"] = False
        branches_tbl["dev"] = dev

    return doc


def _merge_python_section(
    pyproject_path: Path,
    generated: tomlkit.TOMLDocument,
) -> None:
    """Overwrite the `[tool.semantic_release*]` sections in pyproject.toml
    with the generated tables, preserving everything else."""
    if not pyproject_path.is_file():
        raise FileNotFoundError(f"pyproject.toml missing at {pyproject_path}")

    existing = tomlkit.parse(pyproject_path.read_text(encoding="utf-8"))
    tool = existing.setdefault("tool", tomlkit.table())
    gen_tool = generated.get("tool", {})
    gen_sr = gen_tool.get("semantic_release")
    if gen_sr is None:
        raise ValueError("generated release template has no [tool.semantic_release]")

    tool["semantic_release"] = gen_sr
    pyproject_path.write_text(tomlkit.dumps(existing), encoding="utf-8", newline="\n")


def _render_node_releaserc(
    template_text: str,
    *,
    include_npm_plugin: bool,
    tag_format: str,
    branches: tuple[str, ...],
) -> tuple[dict, tuple[str, ...]]:
    """Render .releaserc.json content from the bundled template."""
    data = json.loads(template_text)
    data.pop("_comment", None)

    data["branches"] = list(branches)
    data["tagFormat"] = tag_format

    plugins: list = data.get("plugins", [])
    if include_npm_plugin:
        # Append @semantic-release/npm before @semantic-release/git if not
        # already present.
        names = [entry[0] if isinstance(entry, list) else entry for entry in plugins]
        if "@semantic-release/npm" not in names:
            # Insert before git plugin for correct ordering
            for i, entry in enumerate(plugins):
                entry_name = entry[0] if isinstance(entry, list) else entry
                if entry_name == "@semantic-release/git":
                    plugins.insert(i, "@semantic-release/npm")
                    break
            else:
                plugins.append("@semantic-release/npm")
    else:
        # service path: ensure @semantic-release/npm is NOT present.
        plugins = [
            entry
            for entry in plugins
            if (entry[0] if isinstance(entry, list) else entry) != "@semantic-release/npm"
        ]
    data["plugins"] = plugins

    plugin_names = tuple(entry[0] if isinstance(entry, list) else entry for entry in plugins)
    return data, plugin_names


def _cross_validate_release_patterns(
    exclude_or_release_rules: list,
    scheme: CommitScheme,
) -> None:
    """Assert that every no-release commit type the scheme lists is honored.

    For node: `releaseRules` is a list of dicts with `type` and `release`.
    We walk the list and make sure every type listed as `no_release` in the
    scheme has a rule that sets it to `false`.
    """
    no_release_types = {
        t.split("(")[0].rstrip(":") for t in scheme.no_release if not t.endswith(":")
    }
    rule_map: dict[str, object] = {}
    for rule in exclude_or_release_rules:
        if isinstance(rule, dict) and "type" in rule:
            rule_map[rule["type"]] = rule.get("release")

    missing = []
    for typ in sorted(no_release_types):
        if typ in rule_map and rule_map[typ] not in (False, "false"):
            missing.append(typ)

    if missing:
        raise ReleaseAlignmentError(
            "commit types with release != false that should be no_release: " + ", ".join(missing)
        )


def _detect_python_project_name(pyproject_path: Path) -> str:
    """Read the `[project].name` field from pyproject.toml."""
    data = tomlkit.parse(pyproject_path.read_text(encoding="utf-8"))
    project = data.get("project") or {}
    name = project.get("name")
    if not isinstance(name, str):
        raise ValueError("pyproject.toml has no [project].name")
    return name


def _guess_python_package_name(root: Path, project_name: str) -> str:
    """Guess the importable package name under `src/`.

    Prefers the first directory under `src/` that contains `__init__.py`.
    Falls back to `project_name.replace("-", "_")`.
    """
    src = root / "src"
    if src.is_dir():
        for child in sorted(src.iterdir()):
            if child.is_dir() and (child / "__init__.py").is_file():
                return child.name
    return project_name.replace("-", "_")


def apply(
    detection: Detection,
    root: Path | str = ".",
    *,
    dry_run: bool = False,
    project_name: str | None = None,
) -> ReleaseResult:
    """Write the canonical semantic-release config for *detection*."""
    if detection.language in (Language.AMBIGUOUS, Language.UNKNOWN):
        raise ValueError(f"cannot render release: language is {detection.language}")

    root_path = Path(root).resolve()
    scheme = load_commit_scheme()

    if detection.language == Language.PYTHON:
        pyproject_path = root_path / _PYPROJECT
        if project_name is None:
            project_name = _detect_python_project_name(pyproject_path)
        package_name = _guess_python_package_name(root_path, project_name)
        template_text = _load_repo_template(_PYTHON_TEMPLATE)
        branches = ("main", "dev") if detection.repo_type == RepoType.SERVICE else ("main",)
        generated = _render_python_semantic_release_block(
            template_text,
            branches=branches,
            project_name=project_name,
            package_name=package_name,
        )

        if not dry_run:
            _merge_python_section(pyproject_path, generated)

        return ReleaseResult(
            written=not dry_run,
            template=_PYTHON_TEMPLATE,
            path=pyproject_path,
            plugins=("python-semantic-release",),
        )

    # Node path
    template_text = _load_repo_template(_NODE_TEMPLATE)
    tag_format = f"{project_name}-v${{version}}" if project_name else "v${version}"
    branches = ("main",) if detection.repo_type == RepoType.SERVICE else ("main",)
    data, plugin_names = _render_node_releaserc(
        template_text,
        include_npm_plugin=(detection.repo_type == RepoType.LIBRARY),
        tag_format=tag_format,
        branches=branches,
    )

    # Pull releaseRules out of the commit-analyzer plugin for cross-validation
    for entry in data.get("plugins", []):
        if (
            isinstance(entry, list)
            and entry
            and entry[0] == "@semantic-release/commit-analyzer"
            and len(entry) >= 2
            and isinstance(entry[1], dict)
        ):
            _cross_validate_release_patterns(entry[1].get("releaseRules", []), scheme)

    out_path = root_path / _RELEASERC
    if not dry_run:
        out_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")

    return ReleaseResult(
        written=not dry_run,
        template=_NODE_TEMPLATE,
        path=out_path,
        plugins=plugin_names,
    )
