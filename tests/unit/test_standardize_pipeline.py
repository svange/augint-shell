"""Tests for ai_shell.standardize.pipeline read-only validator (T5-7).

T5-7 reverts T5-5's reusable workflow architecture. Pipeline standardization
is now AI-mediated single-file merge: this Python module is read-only and
provides the deterministic substrate (drift report + canonical job
references) that the skill prose drives Claude through.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from ai_shell.standardize.detection import Language, RepoType
from ai_shell.standardize.pipeline import (
    LEGACY_NAME_MAP,
    LEGACY_PREFIX_PATTERNS,
    DriftReport,
    JobSpec,
    StepMatcher,
    _check_spec,
    _guess_legacy_gate,
    _step_matches,
    canonical_jobs,
    validate,
)

# ── Fixtures ────────────────────────────────────────────────────────────


def _write_python_library(tmp_path: Path) -> None:
    """Make tmp_path look like a python library to detection."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.0.0"\n', encoding="utf-8"
    )


def _write_python_iac(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.0.0"\n', encoding="utf-8"
    )
    (tmp_path / "samconfig.toml").write_text("", encoding="utf-8")


def _write_pipeline(tmp_path: Path, content: str) -> Path:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    pipeline = workflows / "pipeline.yaml"
    pipeline.write_text(textwrap.dedent(content), encoding="utf-8")
    return pipeline


# ── canonical_jobs() ────────────────────────────────────────────────────


class TestCanonicalJobs:
    def test_python_library_returns_5_gates(self):
        refs = canonical_jobs(Language.PYTHON, RepoType.LIBRARY)
        assert set(refs.keys()) == {
            "Code quality",
            "Security",
            "Unit tests",
            "Compliance",
            "Build validation",
        }

    def test_python_iac_returns_6_gates(self):
        refs = canonical_jobs(Language.PYTHON, RepoType.IAC)
        assert "Acceptance tests" in refs
        assert len(refs) == 6

    def test_node_library_returns_5_gates(self):
        refs = canonical_jobs(Language.NODE, RepoType.LIBRARY)
        assert "Acceptance tests" not in refs
        assert len(refs) == 5

    def test_node_iac_returns_6_gates(self):
        refs = canonical_jobs(Language.NODE, RepoType.IAC)
        assert "Acceptance tests" in refs
        assert len(refs) == 6

    def test_jobreference_template_text_loads(self):
        refs = canonical_jobs(Language.PYTHON, RepoType.IAC)
        ref = refs["Unit tests"]
        text = ref.template_text()
        # Inline job, NOT a reusable workflow
        assert "unit-tests:" in text
        assert "name: Unit tests" in text
        assert "workflow_call" not in text

    def test_jobreference_spec_loaded(self):
        refs = canonical_jobs(Language.PYTHON, RepoType.IAC)
        ref = refs["Unit tests"]
        assert ref.spec.gate == "Unit tests"
        assert ref.spec.language == Language.PYTHON
        assert ref.spec.repo_type == RepoType.IAC
        assert any(
            m.kind == "action" and m.matches == "actions/checkout" for m in ref.spec.required_steps
        )


# ── validate() — empty / missing pipeline ──────────────────────────────


class TestValidateEmpty:
    def test_missing_pipeline_returns_not_present(self, tmp_path: Path):
        _write_python_library(tmp_path)
        report = validate(tmp_path)
        assert report.pipeline_present is False
        assert not report.is_clean()

    def test_invalid_yaml_returns_present_but_not_clean(self, tmp_path: Path):
        _write_python_library(tmp_path)
        _write_pipeline(tmp_path, ":\n  - bad\n  not: real yaml: ::: ")
        report = validate(tmp_path)
        assert report.pipeline_present is True


# ── validate() — canonical pipeline ────────────────────────────────────


_CANONICAL_LIBRARY_PIPELINE = """\
name: CI/CD Pipeline
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
jobs:
  code-quality:
    name: Code quality
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
      - name: Set up Python
        uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
        with:
          python-version: '3.12'
      - name: Install UV
        uses: astral-sh/setup-uv@cec208311dfd045dd5311c1add060b2062131d57
      - name: Install
        run: uv sync --frozen --all-extras
      - name: Pre-commit
        run: uv run pre-commit run --all-files
  security:
    name: Security
    needs: [code-quality]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
      - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
      - uses: astral-sh/setup-uv@cec208311dfd045dd5311c1add060b2062131d57
      - run: uv run bandit -r src/
      - run: uv run pip-audit
      - uses: semgrep/semgrep-action@v1
  unit-tests:
    name: Unit tests
    needs: [code-quality]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
      - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
      - uses: astral-sh/setup-uv@cec208311dfd045dd5311c1add060b2062131d57
      - run: uv sync --frozen --all-extras
      - run: |
          uv run pytest \\
            --cov=src --cov-fail-under=80
      - uses: actions/upload-artifact@v7
  compliance:
    name: Compliance
    needs: [code-quality]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
      - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
      - uses: astral-sh/setup-uv@cec208311dfd045dd5311c1add060b2062131d57
      - run: uv run pip-licenses --from=mixed --fail-on 'GPL;AGPL;LGPL' --summary
  build-validation:
    name: Build validation
    needs: [code-quality]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
      - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405
      - uses: astral-sh/setup-uv@cec208311dfd045dd5311c1add060b2062131d57
      - run: uv build
"""


class TestValidateCanonical:
    def test_clean_canonical_pipeline_passes(self, tmp_path: Path):
        _write_python_library(tmp_path)
        _write_pipeline(tmp_path, _CANONICAL_LIBRARY_PIPELINE)
        report = validate(tmp_path)
        assert report.pipeline_present is True
        assert set(report.present) == {
            "Code quality",
            "Security",
            "Unit tests",
            "Compliance",
            "Build validation",
        }
        assert report.missing == ()
        assert report.legacy_candidates == ()
        assert report.spec_failures == ()
        assert report.is_clean() is True

    def test_canonical_with_extra_step_still_clean(self, tmp_path: Path):
        """User can add `Set up test database` etc. anywhere; spec only
        requires the canonical steps in declared order."""
        _write_python_library(tmp_path)
        with_extras = _CANONICAL_LIBRARY_PIPELINE.replace(
            "      - run: uv sync --frozen --all-extras\n      - run: |",
            "      - run: uv sync --frozen --all-extras\n"
            "      - name: Set up test database\n        run: ./scripts/db-up.sh\n"
            "      - run: |",
        )
        _write_pipeline(tmp_path, with_extras)
        report = validate(tmp_path)
        assert report.is_clean() is True


# ── validate() — legacy named pipeline ─────────────────────────────────


class TestValidateLegacy:
    def test_pre_commit_checks_is_legacy_for_code_quality(self, tmp_path: Path):
        _write_python_library(tmp_path)
        _write_pipeline(
            tmp_path,
            """\
            name: x
            on: { push: { branches: [main] } }
            jobs:
              pre-commit:
                name: Pre-commit checks
                runs-on: ubuntu-latest
                steps:
                  - run: echo
            """,
        )
        report = validate(tmp_path)
        assert ("pre-commit", "Pre-commit checks", "Code quality") in report.legacy_candidates
        assert "Code quality" in report.missing

    def test_security_scanning_is_legacy_for_security(self, tmp_path: Path):
        _write_python_library(tmp_path)
        _write_pipeline(
            tmp_path,
            """\
            name: x
            on: { push: { branches: [main] } }
            jobs:
              sec:
                name: Security scanning
                runs-on: ubuntu-latest
                steps: [{ run: echo }]
            """,
        )
        report = validate(tmp_path)
        assert any(g == "Security" for _i, _n, g in report.legacy_candidates)


# ── validate() — parallel post-deploy pattern ──────────────────────────


class TestParallelPostDeploy:
    def test_multiple_e2e_jobs_all_map_to_acceptance_tests(self, tmp_path: Path):
        _write_python_iac(tmp_path)
        _write_pipeline(
            tmp_path,
            """\
            name: x
            on: { push: { branches: [main, dev] } }
            jobs:
              e2e-smoke:
                name: E2E Smoke Tests
                runs-on: ubuntu-latest
                steps: [{ run: echo }]
              e2e-payment:
                name: E2E Payment Tests
                runs-on: ubuntu-latest
                steps: [{ run: echo }]
              e2e-admin:
                name: E2E Admin Tests
                runs-on: ubuntu-latest
                steps: [{ run: echo }]
            """,
        )
        report = validate(tmp_path)
        guesses = [g for _i, _n, g in report.legacy_candidates]
        assert guesses.count("Acceptance tests") == 3
        assert "Acceptance tests" in report.missing

    def test_integration_and_smoke_both_map_to_acceptance(self, tmp_path: Path):
        _write_python_iac(tmp_path)
        _write_pipeline(
            tmp_path,
            """\
            name: x
            on: { push: { branches: [main, dev] } }
            jobs:
              int:
                name: Integration tests
                runs-on: ubuntu-latest
                steps: [{ run: echo }]
              smoke:
                name: Smoke tests
                runs-on: ubuntu-latest
                steps: [{ run: echo }]
            """,
        )
        report = validate(tmp_path)
        names = [name for _i, name, _g in report.legacy_candidates]
        assert "Integration tests" in names
        assert "Smoke tests" in names


# ── validate() — custom jobs ───────────────────────────────────────────


class TestCustomJobs:
    def test_custom_job_listed_for_preservation(self, tmp_path: Path):
        _write_python_library(tmp_path)
        _write_pipeline(
            tmp_path,
            """\
            name: x
            on: { push: { branches: [main] } }
            jobs:
              deploy-test-stack:
                name: Deploy test stack
                runs-on: ubuntu-latest
                steps: [{ run: echo }]
              release:
                name: Semantic release
                needs: [code-quality]
                runs-on: ubuntu-latest
                steps: [{ run: echo }]
            """,
        )
        report = validate(tmp_path)
        assert "deploy-test-stack" in report.custom_jobs
        assert "release" in report.custom_jobs


# ── Spec matching unit tests ───────────────────────────────────────────


class TestStepMatches:
    def test_action_substring_match(self):
        step = {"uses": "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd"}
        m = StepMatcher(kind="action", matches="actions/checkout")
        assert _step_matches(step, m)

    def test_action_no_match(self):
        step = {"uses": "actions/setup-node@v4"}
        m = StepMatcher(kind="action", matches="actions/checkout")
        assert not _step_matches(step, m)

    def test_run_regex_match(self):
        step = {"run": "uv run pytest --cov=src --cov-fail-under=80"}
        m = StepMatcher(kind="run", matches_regex=r"uv run pytest .*--cov-fail-under=80")
        assert _step_matches(step, m)

    def test_run_regex_spans_continuation_lines(self):
        """Multi-line run blocks like ``uv run pytest \\\\\\n --cov...`` must match."""
        step = {"run": "uv run pytest \\\n  --cov=src --cov-fail-under=80\n"}
        m = StepMatcher(kind="run", matches_regex=r"uv run pytest .*--cov-fail-under=80")
        assert _step_matches(step, m)


class TestCheckSpec:
    @pytest.fixture
    def py_unit_spec(self) -> JobSpec:
        return JobSpec(
            gate="Unit tests",
            language=Language.PYTHON,
            repo_type=RepoType.LIBRARY,
            required_steps=(
                StepMatcher(kind="action", matches="actions/checkout"),
                StepMatcher(kind="action", matches="actions/setup-python"),
                StepMatcher(kind="run", matches_regex=r"uv run pytest .*--cov-fail-under=80"),
            ),
        )

    def test_minimum_spec_satisfied(self, py_unit_spec: JobSpec):
        job = {
            "steps": [
                {"uses": "actions/checkout@v6"},
                {"uses": "actions/setup-python@v6"},
                {"run": "uv run pytest --cov-fail-under=80"},
            ]
        }
        assert _check_spec(job, py_unit_spec) is None

    def test_extras_allowed_anywhere(self, py_unit_spec: JobSpec):
        job = {
            "steps": [
                {"uses": "actions/checkout@v6"},
                {"name": "Set up test DB", "run": "./db-up.sh"},
                {"uses": "actions/setup-python@v6"},
                {"name": "Slack notify", "run": "curl ..."},
                {"run": "uv run pytest --cov-fail-under=80"},
            ]
        }
        assert _check_spec(job, py_unit_spec) is None

    def test_missing_required_step(self, py_unit_spec: JobSpec):
        job = {
            "steps": [
                {"uses": "actions/checkout@v6"},
                {"uses": "actions/setup-python@v6"},
                # missing pytest run
            ]
        }
        result = _check_spec(job, py_unit_spec)
        assert result is not None
        assert "pytest" in result

    def test_out_of_order_required_steps_fail(self, py_unit_spec: JobSpec):
        job = {
            "steps": [
                {"uses": "actions/setup-python@v6"},
                {"uses": "actions/checkout@v6"},  # after setup-python
                {"run": "uv run pytest --cov-fail-under=80"},
            ]
        }
        result = _check_spec(job, py_unit_spec)
        assert result is not None  # checkout missing in declared order


# ── Legacy name guesser ────────────────────────────────────────────────


class TestGuessLegacyGate:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Pre-commit checks", "Code quality"),
            ("Quality checks", "Code quality"),
            ("Security scanning", "Security"),
            ("SAST scanning", "Security"),
            ("License compliance", "Compliance"),
            ("Validate SAM template", "Build validation"),
            ("Integration tests", "Acceptance tests"),
            ("Smoke tests", "Acceptance tests"),
            ("E2E Smoke Tests", "Acceptance tests"),
            ("E2E Payment Tests", "Acceptance tests"),
        ],
    )
    def test_known_legacy_names(self, name: str, expected: str):
        assert _guess_legacy_gate(name) == expected

    def test_unknown_name_returns_none(self):
        assert _guess_legacy_gate("My weird custom job") is None

    def test_canonical_name_returns_none(self):
        assert _guess_legacy_gate("Code quality") is None


class TestLegacyMaps:
    def test_legacy_name_map_has_eight_or_more_entries(self):
        assert len(LEGACY_NAME_MAP) >= 8

    def test_legacy_prefix_patterns_cover_e2e_and_smoke(self):
        prefixes = [p for p, _g in LEGACY_PREFIX_PATTERNS]
        assert any("e2e" in p for p in prefixes)
        assert any("smoke" in p for p in prefixes)
        assert any("integration" in p for p in prefixes)


# ── DriftReport ────────────────────────────────────────────────────────


class TestDriftReport:
    def test_to_dict_round_trips(self, tmp_path: Path):
        report = DriftReport(
            pipeline_path=tmp_path / "pipeline.yaml",
            pipeline_present=True,
            present=("Code quality",),
            missing=("Security",),
            legacy_candidates=(("sec", "Security scanning", "Security"),),
            custom_jobs=("release",),
        )
        d = report.to_dict()
        assert d["present"] == ["Code quality"]
        assert d["missing"] == ["Security"]
        assert d["legacy_candidates"] == [
            {"job_id": "sec", "current_name": "Security scanning", "gate_guess": "Security"}
        ]
        assert d["custom_jobs"] == ["release"]
        assert d["is_clean"] is False

    def test_is_clean_requires_no_drift(self, tmp_path: Path):
        clean = DriftReport(
            pipeline_path=tmp_path / "pipeline.yaml",
            pipeline_present=True,
            present=("Code quality", "Security"),
        )
        assert clean.is_clean()

    def test_missing_means_not_clean(self, tmp_path: Path):
        report = DriftReport(
            pipeline_path=tmp_path / "pipeline.yaml",
            pipeline_present=True,
            missing=("Security",),
        )
        assert not report.is_clean()


# ── Removed-API regression ────────────────────────────────────────────


class TestRemovedApi:
    """Regression: T5-7 removed the write-side API. Imports must fail."""

    def test_apply_is_gone(self):
        from ai_shell.standardize import pipeline as p

        assert not hasattr(p, "apply")
        assert not hasattr(p, "PipelineDriftError")
        assert not hasattr(p, "_validate_existing_pipeline")
        assert not hasattr(p, "_referenced_gate_names")
        assert not hasattr(p, "_GATE_SLUG")
        assert not hasattr(p, "_gate_filename")
