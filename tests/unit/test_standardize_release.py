"""Tests for ai_shell.standardize.release generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import tomlkit

from ai_shell.standardize.detection import Detection, Language, RepoType
from ai_shell.standardize.release import ReleaseAlignmentError, apply


def _det(lang: Language, typ: RepoType) -> Detection:
    return Detection(
        language=lang,
        repo_type=typ,
        language_evidence=(),
        repo_type_evidence=(),
    )


def _write_pyproject(tmp_path: Path, name: str = "myproject", with_package: bool = True) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    if with_package:
        pkg = tmp_path / "src" / name.replace("-", "_")
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text('__version__ = "0.0.0"\n', encoding="utf-8")


class TestPythonLibrary:
    def test_writes_tool_semantic_release(self, tmp_path: Path):
        _write_pyproject(tmp_path)
        apply(_det(Language.PYTHON, RepoType.LIBRARY), tmp_path)
        text = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
        doc = tomlkit.parse(text)
        sr = doc["tool"]["semantic_release"]
        assert "tag_format" in sr
        assert sr["tag_format"] == "myproject-v{version}"

    def test_branches_main_only(self, tmp_path: Path):
        _write_pyproject(tmp_path)
        apply(_det(Language.PYTHON, RepoType.LIBRARY), tmp_path)
        doc = tomlkit.parse((tmp_path / "pyproject.toml").read_text(encoding="utf-8"))
        branches = doc["tool"]["semantic_release"]["branches"]
        assert "main" in branches
        assert "dev" not in branches


class TestPythonIac:
    def test_adds_dev_branch(self, tmp_path: Path):
        _write_pyproject(tmp_path)
        apply(_det(Language.PYTHON, RepoType.SERVICE), tmp_path)
        doc = tomlkit.parse((tmp_path / "pyproject.toml").read_text(encoding="utf-8"))
        branches = doc["tool"]["semantic_release"]["branches"]
        assert "main" in branches
        assert "dev" in branches
        assert branches["dev"]["match"] == "dev"


class TestNodeLibrary:
    def test_includes_npm_plugin(self, tmp_path: Path):
        apply(_det(Language.NODE, RepoType.LIBRARY), tmp_path, project_name="mypkg")
        data = json.loads((tmp_path / ".releaserc.json").read_text(encoding="utf-8"))
        plugin_names = [entry[0] if isinstance(entry, list) else entry for entry in data["plugins"]]
        assert "@semantic-release/npm" in plugin_names

    def test_tag_format_uses_project_name(self, tmp_path: Path):
        apply(_det(Language.NODE, RepoType.LIBRARY), tmp_path, project_name="mypkg")
        data = json.loads((tmp_path / ".releaserc.json").read_text(encoding="utf-8"))
        assert data["tagFormat"] == "mypkg-v${version}"


class TestNodeIac:
    def test_excludes_npm_plugin(self, tmp_path: Path):
        apply(_det(Language.NODE, RepoType.SERVICE), tmp_path, project_name="lls-web")
        data = json.loads((tmp_path / ".releaserc.json").read_text(encoding="utf-8"))
        plugin_names = [entry[0] if isinstance(entry, list) else entry for entry in data["plugins"]]
        assert "@semantic-release/npm" not in plugin_names

    def test_main_only_branches(self, tmp_path: Path):
        apply(_det(Language.NODE, RepoType.SERVICE), tmp_path, project_name="lls-web")
        data = json.loads((tmp_path / ".releaserc.json").read_text(encoding="utf-8"))
        assert data["branches"] == ["main"]

    def test_tag_format_for_lls_web(self, tmp_path: Path):
        apply(_det(Language.NODE, RepoType.SERVICE), tmp_path, project_name="lls-web")
        data = json.loads((tmp_path / ".releaserc.json").read_text(encoding="utf-8"))
        assert data["tagFormat"] == "lls-web-v${version}"


class TestNoAdaptProseInOutput:
    """Regression for T5-3: release templates must not leak ADAPT prose."""

    def test_python_pyproject_has_no_adapt_comments(self, tmp_path: Path):
        _write_pyproject(tmp_path)
        apply(_det(Language.PYTHON, RepoType.LIBRARY), tmp_path)
        text = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
        assert "ADAPT before" not in text
        assert "ADAPT: " not in text

    def test_node_releaserc_has_no_adapt_comment_field(self, tmp_path: Path):
        apply(_det(Language.NODE, RepoType.LIBRARY), tmp_path, project_name="mypkg")
        data = json.loads((tmp_path / ".releaserc.json").read_text(encoding="utf-8"))
        assert "_comment" not in data


class TestCrossValidation:
    def test_raises_when_no_release_type_promoted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from ai_shell.standardize import release as mod

        bad_template = json.dumps(
            {
                "branches": ["main"],
                "plugins": [
                    [
                        "@semantic-release/commit-analyzer",
                        {
                            "releaseRules": [
                                # chore is listed as no_release in commit-scheme.json
                                # but here we claim it triggers a patch release
                                {"type": "chore", "release": "patch"},
                            ]
                        },
                    ],
                    "@semantic-release/git",
                ],
            }
        )
        original = mod._load_repo_template

        def fake(name: str) -> str:
            if name.endswith(".releaserc.json"):
                return bad_template
            return original(name)

        monkeypatch.setattr(mod, "_load_repo_template", fake)
        with pytest.raises(ReleaseAlignmentError):
            apply(
                _det(Language.NODE, RepoType.LIBRARY),
                tmp_path,
                project_name="bad",
            )
