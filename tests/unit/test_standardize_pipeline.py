"""Tests for ai_shell.standardize.pipeline generator."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_shell.standardize.detection import Detection, Language, RepoType
from ai_shell.standardize.gates import load_gates
from ai_shell.standardize.pipeline import (
    PipelineDriftError,
    _extract_job_names,
    _validate_job_names,
    apply,
)


def _det(lang: Language, typ: RepoType) -> Detection:
    return Detection(
        language=lang,
        repo_type=typ,
        language_evidence=("pyproject.toml" if lang == Language.PYTHON else "package.json",),
        repo_type_evidence=("samconfig.toml",) if typ == RepoType.IAC else (),
    )


class TestApplyEachCombination:
    @pytest.mark.parametrize(
        ("lang", "typ"),
        [
            (Language.PYTHON, RepoType.LIBRARY),
            (Language.PYTHON, RepoType.IAC),
            (Language.NODE, RepoType.LIBRARY),
            (Language.NODE, RepoType.IAC),
        ],
    )
    def test_writes_pipeline_file(self, tmp_path: Path, lang: Language, typ: RepoType):
        result = apply(_det(lang, typ), tmp_path)
        assert result.written is True
        assert result.path.is_file()
        content = result.path.read_text(encoding="utf-8")
        assert "name: CI/CD Pipeline" in content

    @pytest.mark.parametrize(
        ("lang", "typ"),
        [
            (Language.PYTHON, RepoType.LIBRARY),
            (Language.NODE, RepoType.LIBRARY),
        ],
    )
    def test_library_has_5_pre_merge_gates(self, tmp_path: Path, lang: Language, typ: RepoType):
        result = apply(_det(lang, typ), tmp_path)
        content = result.path.read_text(encoding="utf-8")
        gates = load_gates()
        for gate in gates.pre_merge:
            assert f"name: {gate}" in content, f"{gate} missing from {result.template}"
        # Library must NOT have Acceptance tests
        assert "name: Acceptance tests" not in content

    @pytest.mark.parametrize(
        ("lang", "typ"),
        [
            (Language.PYTHON, RepoType.IAC),
            (Language.NODE, RepoType.IAC),
        ],
    )
    def test_iac_has_all_6_gates(self, tmp_path: Path, lang: Language, typ: RepoType):
        result = apply(_det(lang, typ), tmp_path)
        content = result.path.read_text(encoding="utf-8")
        gates = load_gates()
        for gate in gates.all_names():
            assert f"name: {gate}" in content, f"{gate} missing from {result.template}"

    @pytest.mark.parametrize(
        ("lang", "typ"),
        [
            (Language.PYTHON, RepoType.IAC),
            (Language.NODE, RepoType.IAC),
        ],
    )
    def test_iac_acceptance_tests_guarded_by_dev_push(
        self, tmp_path: Path, lang: Language, typ: RepoType
    ):
        result = apply(_det(lang, typ), tmp_path)
        content = result.path.read_text(encoding="utf-8")
        # Find the acceptance-tests job block and ensure it has the right `if:`.
        assert "name: Acceptance tests" in content
        assert "github.ref == 'refs/heads/dev'" in content
        assert "github.event_name == 'push'" in content

    def test_dry_run_does_not_write(self, tmp_path: Path):
        result = apply(_det(Language.PYTHON, RepoType.LIBRARY), tmp_path, dry_run=True)
        assert result.written is False
        assert not result.path.exists()

    @pytest.mark.parametrize(
        ("lang", "typ"),
        [
            (Language.PYTHON, RepoType.IAC),
            (Language.NODE, RepoType.IAC),
        ],
    )
    def test_iac_writes_nightly_promotion_template(
        self, tmp_path: Path, lang: Language, typ: RepoType
    ):
        result = apply(_det(lang, typ), tmp_path)
        assert result.nightly_path is not None
        assert result.nightly_path.is_file()
        content = result.nightly_path.read_text(encoding="utf-8")
        # Must have the nightly cron, dispatch logic, and merge (not squash)
        assert "cron: '0 7 * * *'" in content
        assert "workflow_dispatch" in content
        assert "--merge" in content
        assert "--squash" not in content

    @pytest.mark.parametrize(
        ("lang", "typ"),
        [
            (Language.PYTHON, RepoType.LIBRARY),
            (Language.NODE, RepoType.LIBRARY),
        ],
    )
    def test_library_does_not_write_nightly(self, tmp_path: Path, lang: Language, typ: RepoType):
        result = apply(_det(lang, typ), tmp_path)
        assert result.nightly_path is None
        nightly_file = tmp_path / ".github" / "workflows" / "promote-dev-to-main.nightly.yml"
        assert not nightly_file.exists()


class TestValidateJobNames:
    def test_accepts_canonical_vocabulary(self):
        gates = load_gates()
        yaml_text = "jobs:\n"
        for g in gates.pre_merge:
            yaml_text += f"  {g.lower().replace(' ', '-')}:\n    name: {g}\n"
        _validate_job_names(
            yaml_text,
            gates,
            _det(Language.PYTHON, RepoType.LIBRARY),
        )  # no raise

    def test_raises_on_missing_gate(self):
        gates = load_gates()
        yaml_text = "jobs:\n  code-quality:\n    name: Code quality\n"
        with pytest.raises(PipelineDriftError) as exc:
            _validate_job_names(yaml_text, gates, _det(Language.PYTHON, RepoType.LIBRARY))
        assert "missing canonical gates" in str(exc.value)

    def test_raises_on_case_drifted_gate(self):
        gates = load_gates()
        # All 5 gates present but Code Quality has wrong case
        yaml_text = "jobs:\n"
        for g in gates.pre_merge:
            rendered = "Code Quality" if g == "Code quality" else g
            yaml_text += f"  x:\n    name: {rendered}\n"
        with pytest.raises(PipelineDriftError) as exc:
            _validate_job_names(yaml_text, gates, _det(Language.PYTHON, RepoType.LIBRARY))
        assert "case-drifted" in str(exc.value) or "missing" in str(exc.value)


class TestExtractJobNames:
    def test_extracts_only_top_level_job_names(self):
        yaml_text = (
            "name: CI/CD Pipeline\n"
            "jobs:\n"
            "  a:\n    name: Code quality\n"
            "  b:\n"
            "    name: Security\n"
            "    steps:\n"
            "      - name: Checkout\n"
        )
        names = _extract_job_names(yaml_text)
        assert "Code quality" in names
        assert "Security" in names
        # Step names must NOT be treated as job names
        assert "Checkout" not in names


class TestRaisesOnAmbiguous:
    def test_ambiguous_language_raises(self, tmp_path: Path):
        det = Detection(
            language=Language.AMBIGUOUS,
            repo_type=RepoType.LIBRARY,
            language_evidence=("pyproject.toml", "package.json"),
            repo_type_evidence=(),
        )
        with pytest.raises(ValueError):
            apply(det, tmp_path)
