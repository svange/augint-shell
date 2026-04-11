"""Tests for ai_shell.standardize.pipeline merge-aware generator (T5-5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_shell.standardize.detection import Detection, Language, RepoType
from ai_shell.standardize.gates import load_gates
from ai_shell.standardize.pipeline import (
    _GATE_SLUG,
    PipelineDriftError,
    _gate_filename,
    _referenced_gate_names,
    _validate_existing_pipeline,
    apply,
)


def _det(lang: Language, typ: RepoType) -> Detection:
    return Detection(
        language=lang,
        repo_type=typ,
        language_evidence=("pyproject.toml" if lang == Language.PYTHON else "package.json",),
        repo_type_evidence=("samconfig.toml",) if typ == RepoType.IAC else (),
    )


# ── First-run (scaffold) behavior ───────────────────────────────────────


class TestFirstRun:
    @pytest.mark.parametrize(
        ("lang", "typ"),
        [
            (Language.PYTHON, RepoType.LIBRARY),
            (Language.PYTHON, RepoType.IAC),
            (Language.NODE, RepoType.LIBRARY),
            (Language.NODE, RepoType.IAC),
        ],
    )
    def test_scaffolds_pipeline_yaml(self, tmp_path: Path, lang: Language, typ: RepoType):
        result = apply(_det(lang, typ), tmp_path)
        assert result.scaffold_written is True
        assert result.pipeline_path.is_file()
        content = result.pipeline_path.read_text(encoding="utf-8")
        assert "name: CI/CD Pipeline" in content

    @pytest.mark.parametrize(
        ("lang", "typ"),
        [
            (Language.PYTHON, RepoType.LIBRARY),
            (Language.NODE, RepoType.LIBRARY),
        ],
    )
    def test_library_scaffold_references_5_gates(
        self, tmp_path: Path, lang: Language, typ: RepoType
    ):
        result = apply(_det(lang, typ), tmp_path)
        content = result.pipeline_path.read_text(encoding="utf-8")
        gates = load_gates()
        for gate in gates.pre_merge:
            slug = _GATE_SLUG[gate]
            assert f"uses: ./.github/workflows/_gate-{slug}.yaml" in content
        # Library must NOT reference acceptance-tests
        assert "_gate-acceptance-tests.yaml" not in content

    @pytest.mark.parametrize(
        ("lang", "typ"),
        [
            (Language.PYTHON, RepoType.IAC),
            (Language.NODE, RepoType.IAC),
        ],
    )
    def test_iac_scaffold_references_all_6_gates(
        self, tmp_path: Path, lang: Language, typ: RepoType
    ):
        result = apply(_det(lang, typ), tmp_path)
        content = result.pipeline_path.read_text(encoding="utf-8")
        gates = load_gates()
        for gate in gates.all_names():
            slug = _GATE_SLUG[gate]
            assert f"uses: ./.github/workflows/_gate-{slug}.yaml" in content


class TestGateFilesAlwaysRegenerated:
    @pytest.mark.parametrize(
        ("lang", "typ", "expected_count"),
        [
            (Language.PYTHON, RepoType.LIBRARY, 5),
            (Language.PYTHON, RepoType.IAC, 6),
            (Language.NODE, RepoType.LIBRARY, 5),
            (Language.NODE, RepoType.IAC, 6),
        ],
    )
    def test_gate_files_written(
        self,
        tmp_path: Path,
        lang: Language,
        typ: RepoType,
        expected_count: int,
    ):
        result = apply(_det(lang, typ), tmp_path)
        assert len(result.gate_files) == expected_count
        for gate_file in result.gate_files:
            assert gate_file.is_file()
            content = gate_file.read_text(encoding="utf-8")
            assert "on:" in content
            assert "workflow_call:" in content

    def test_gate_file_names_match_canonical_slugs(self, tmp_path: Path):
        result = apply(_det(Language.PYTHON, RepoType.IAC), tmp_path)
        names = {gf.name for gf in result.gate_files}
        expected = {
            "_gate-code-quality.yaml",
            "_gate-security.yaml",
            "_gate-unit-tests.yaml",
            "_gate-compliance.yaml",
            "_gate-build-validation.yaml",
            "_gate-acceptance-tests.yaml",
        }
        assert names == expected

    def test_python_iac_build_validation_has_sam_logic(self, tmp_path: Path):
        """iac build-validation uses a different template from library."""
        apply(_det(Language.PYTHON, RepoType.IAC), tmp_path)
        bv = tmp_path / ".github" / "workflows" / "_gate-build-validation.yaml"
        content = bv.read_text(encoding="utf-8")
        assert "sam build" in content
        assert "cdk synth" in content
        assert "terraform" in content.lower()

    def test_python_library_build_validation_is_uv_build(self, tmp_path: Path):
        apply(_det(Language.PYTHON, RepoType.LIBRARY), tmp_path)
        bv = tmp_path / ".github" / "workflows" / "_gate-build-validation.yaml"
        content = bv.read_text(encoding="utf-8")
        assert "uv build" in content
        assert "sam build" not in content


# ── Subsequent-run (preserve) behavior ──────────────────────────────────


class TestSecondRunPreservesPipeline:
    def test_pipeline_yaml_preserved_verbatim(self, tmp_path: Path):
        """User's pipeline.yaml must not be mutated on a second run."""
        # First run: scaffold
        apply(_det(Language.PYTHON, RepoType.LIBRARY), tmp_path)
        pipeline_path = tmp_path / ".github" / "workflows" / "pipeline.yaml"
        original = pipeline_path.read_text(encoding="utf-8")

        # User adds a custom job that wires between build-validation and their own suite
        customized = original.replace(
            "  release:",
            "  deploy-test-stack:\n"
            "    name: Deploy test stack\n"
            "    needs: [build-validation]\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: echo custom\n"
            "\n"
            "  release:",
            1,
        )
        pipeline_path.write_text(customized, encoding="utf-8")

        # Second run
        result = apply(_det(Language.PYTHON, RepoType.LIBRARY), tmp_path)
        assert result.scaffold_written is False
        # The custom block must still be present after the run
        after = pipeline_path.read_text(encoding="utf-8")
        assert "deploy-test-stack" in after
        assert "Deploy test stack" in after
        assert after == customized

    def test_second_run_refreshes_gate_files(self, tmp_path: Path):
        """Gate files are tool-owned; user edits to them are overwritten."""
        apply(_det(Language.PYTHON, RepoType.LIBRARY), tmp_path)
        code_quality = tmp_path / ".github" / "workflows" / "_gate-code-quality.yaml"
        code_quality.write_text("# user tampered\n", encoding="utf-8")

        apply(_det(Language.PYTHON, RepoType.LIBRARY), tmp_path)
        restored = code_quality.read_text(encoding="utf-8")
        assert "name: Code quality" in restored
        assert "# user tampered" not in restored

    def test_custom_job_can_reference_acceptance_tests(self, tmp_path: Path):
        """ai-lls-lib-like scenario: user wires custom post-deploy work then
        the canonical Acceptance tests gate on an iac repo."""
        apply(_det(Language.PYTHON, RepoType.IAC), tmp_path)
        pipeline_path = tmp_path / ".github" / "workflows" / "pipeline.yaml"
        original = pipeline_path.read_text(encoding="utf-8")

        # Rewrite acceptance-tests to depend on a new custom job
        customized = original.replace(
            "  acceptance-tests:\n"
            "    name: Acceptance tests\n"
            "    needs: [code-quality, security, unit-tests, compliance, build-validation]\n",
            "  integration-tests:\n"
            "    name: Integration tests\n"
            "    needs: [build-validation]\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: echo integration\n"
            "\n"
            "  acceptance-tests:\n"
            "    name: Acceptance tests\n"
            "    needs: [integration-tests]\n",
        )
        pipeline_path.write_text(customized, encoding="utf-8")

        # Second run — acceptance-tests still references a canonical
        # `uses:`, so the validator must accept it.
        result = apply(_det(Language.PYTHON, RepoType.IAC), tmp_path)
        assert result.scaffold_written is False


class TestSecondRunValidation:
    def test_raises_when_canonical_gate_removed(self, tmp_path: Path):
        apply(_det(Language.PYTHON, RepoType.LIBRARY), tmp_path)
        pipeline_path = tmp_path / ".github" / "workflows" / "pipeline.yaml"
        content = pipeline_path.read_text(encoding="utf-8")
        # Remove the build-validation job
        stripped = content.replace(
            "  build-validation:\n"
            "    name: Build validation\n"
            "    needs: [code-quality]\n"
            "    uses: ./.github/workflows/_gate-build-validation.yaml\n"
            "    secrets: inherit\n\n",
            "",
        )
        pipeline_path.write_text(stripped, encoding="utf-8")
        with pytest.raises(PipelineDriftError) as exc:
            apply(_det(Language.PYTHON, RepoType.LIBRARY), tmp_path)
        assert "Build validation" in str(exc.value)

    def test_error_message_is_actionable(self, tmp_path: Path):
        apply(_det(Language.PYTHON, RepoType.LIBRARY), tmp_path)
        pipeline_path = tmp_path / ".github" / "workflows" / "pipeline.yaml"
        pipeline_path.write_text("name: x\njobs: {}\n", encoding="utf-8")
        with pytest.raises(PipelineDriftError) as exc:
            apply(_det(Language.PYTHON, RepoType.LIBRARY), tmp_path)
        msg = str(exc.value)
        # All 5 canonical gates should be listed as missing
        assert "Code quality" in msg
        assert "Security" in msg
        # And the error should give a copyable job block hint
        assert "uses: ./.github/workflows/_gate-" in msg


# ── Nightly promotion ──────────────────────────────────────────────────


class TestNightlyPromotion:
    @pytest.mark.parametrize(
        ("lang", "typ"),
        [
            (Language.PYTHON, RepoType.IAC),
            (Language.NODE, RepoType.IAC),
        ],
    )
    def test_iac_writes_nightly(self, tmp_path: Path, lang: Language, typ: RepoType):
        result = apply(_det(lang, typ), tmp_path)
        assert result.nightly_path is not None
        assert result.nightly_path.is_file()
        content = result.nightly_path.read_text(encoding="utf-8")
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
        nightly = tmp_path / ".github" / "workflows" / "promote-dev-to-main.nightly.yml"
        assert not nightly.exists()


# ── Reference parser ───────────────────────────────────────────────────


class TestReferencedGateNames:
    def test_extracts_canonical_references(self):
        data = {
            "jobs": {
                "cq": {"uses": "./.github/workflows/_gate-code-quality.yaml"},
                "sec": {"uses": "./.github/workflows/_gate-security.yaml"},
                "custom": {"runs-on": "ubuntu-latest", "steps": []},
            }
        }
        names = _referenced_gate_names(data)
        assert names == {"Code quality", "Security"}

    def test_ignores_non_canonical_uses(self):
        data = {
            "jobs": {
                "other": {"uses": "./.github/workflows/something-else.yaml"},
                "external": {"uses": "org/repo/.github/workflows/x.yaml@main"},
            }
        }
        assert _referenced_gate_names(data) == set()


# ── Validator unit tests ───────────────────────────────────────────────


class TestValidateExistingPipeline:
    def test_accepts_all_gates_referenced(self, tmp_path: Path):
        text = (
            "name: p\njobs:\n"
            "  cq:\n    uses: ./.github/workflows/_gate-code-quality.yaml\n"
            "  sec:\n    uses: ./.github/workflows/_gate-security.yaml\n"
            "  ut:\n    uses: ./.github/workflows/_gate-unit-tests.yaml\n"
            "  comp:\n    uses: ./.github/workflows/_gate-compliance.yaml\n"
            "  bv:\n    uses: ./.github/workflows/_gate-build-validation.yaml\n"
        )
        # Library expected gates
        _validate_existing_pipeline(
            text,
            (
                "Code quality",
                "Security",
                "Unit tests",
                "Compliance",
                "Build validation",
            ),
            tmp_path / "pipeline.yaml",
        )

    def test_raises_on_invalid_yaml(self, tmp_path: Path):
        with pytest.raises(PipelineDriftError):
            _validate_existing_pipeline(
                ":\n  - bad\nthis is: not, valid: yaml",
                ("Code quality",),
                tmp_path / "pipeline.yaml",
            )

    def test_raises_on_non_mapping_top_level(self, tmp_path: Path):
        with pytest.raises(PipelineDriftError):
            _validate_existing_pipeline(
                "- item1\n- item2\n",
                ("Code quality",),
                tmp_path / "pipeline.yaml",
            )


# ── Ambiguous language ─────────────────────────────────────────────────


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


# ── Helpers ────────────────────────────────────────────────────────────


class TestGateFilename:
    def test_canonical_slug_mapping(self):
        assert _gate_filename("Code quality") == "_gate-code-quality.yaml"
        assert _gate_filename("Build validation") == "_gate-build-validation.yaml"
        assert _gate_filename("Acceptance tests") == "_gate-acceptance-tests.yaml"
