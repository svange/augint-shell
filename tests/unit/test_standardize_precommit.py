"""Tests for ai_shell.standardize.precommit generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_shell.standardize.detection import Detection, Language, RepoType
from ai_shell.standardize.precommit import apply


def _det(lang: Language) -> Detection:
    return Detection(
        language=lang,
        repo_type=RepoType.LIBRARY,
        language_evidence=(),
        repo_type_evidence=(),
    )


class TestPythonPath:
    def test_writes_pre_commit_config(self, tmp_path: Path):
        apply(_det(Language.PYTHON), tmp_path)
        cfg = tmp_path / ".pre-commit-config.yaml"
        assert cfg.is_file()
        content = cfg.read_text(encoding="utf-8")
        assert "ruff" in content
        assert "mypy" in content

    def test_idempotent(self, tmp_path: Path):
        apply(_det(Language.PYTHON), tmp_path)
        cfg = tmp_path / ".pre-commit-config.yaml"
        first = cfg.read_text(encoding="utf-8")
        apply(_det(Language.PYTHON), tmp_path)
        assert cfg.read_text(encoding="utf-8") == first


class TestNodePath:
    def test_writes_husky_hook_and_lint_staged(self, tmp_path: Path):
        (tmp_path / "package.json").write_text('{"name": "x"}', encoding="utf-8")
        result = apply(_det(Language.NODE), tmp_path)
        hook = tmp_path / ".husky" / "pre-commit"
        lint_staged = tmp_path / "lint-staged.config.json"
        assert hook.is_file()
        assert lint_staged.is_file()
        assert result.language == Language.NODE

    def test_husky_hook_runs_lint_staged(self, tmp_path: Path):
        (tmp_path / "package.json").write_text('{"name": "x"}', encoding="utf-8")
        apply(_det(Language.NODE), tmp_path)
        content = (tmp_path / ".husky" / "pre-commit").read_text(encoding="utf-8")
        assert "lint-staged" in content

    def test_merges_prepare_script(self, tmp_path: Path):
        (tmp_path / "package.json").write_text(
            '{"name": "x", "scripts": {"build": "vite build"}}', encoding="utf-8"
        )
        apply(_det(Language.NODE), tmp_path)
        data = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
        assert data["scripts"]["prepare"] == "husky install"
        assert data["scripts"]["build"] == "vite build"  # preserved

    def test_idempotent_on_second_run(self, tmp_path: Path):
        (tmp_path / "package.json").write_text(
            '{"name": "x", "scripts": {"prepare": "husky install"}}',
            encoding="utf-8",
        )
        apply(_det(Language.NODE), tmp_path)
        data = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
        # Still set, not duplicated
        assert data["scripts"] == {"prepare": "husky install"}

    def test_lint_staged_matches_ts_tsx_vue(self, tmp_path: Path):
        (tmp_path / "package.json").write_text('{"name": "x"}', encoding="utf-8")
        apply(_det(Language.NODE), tmp_path)
        data = json.loads((tmp_path / "lint-staged.config.json").read_text(encoding="utf-8"))
        ts_rule_key = next(k for k in data if "ts" in k and "tsx" in k and "vue" in k)
        assert "eslint --fix" in data[ts_rule_key]
        assert "prettier --write" in data[ts_rule_key]


class TestUnknownLanguageRaises:
    def test_unknown_raises(self, tmp_path: Path):
        with pytest.raises(ValueError):
            apply(_det(Language.UNKNOWN), tmp_path)
