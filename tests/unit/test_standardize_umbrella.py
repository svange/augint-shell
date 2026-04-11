"""Tests for ai_shell.standardize.umbrella orchestrator and verify."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ai_shell.standardize.umbrella import StepStatus, run_all


def _make_python_library(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "myproject"\nversion = "0.0.0"\n', encoding="utf-8"
    )
    pkg = tmp_path / "src" / "myproject"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "0.0.0"\n', encoding="utf-8")


class TestRunAllPythonLibrary:
    def test_detect_step_ok(self, tmp_path: Path):
        _make_python_library(tmp_path)
        with patch("ai_shell.standardize.umbrella._run_gh") as mock_gh:
            mock_gh.return_value = (0, "", "")
            with patch("ai_shell.standardize.umbrella.verify.run") as mock_v:
                mock_v.return_value = ()
                results = run_all(tmp_path)
        step_names = [r.step for r in results]
        assert step_names[0] == "detect"
        assert results[0].status == StepStatus.OK
        assert "python/library" in results[0].message

    def test_content_generation_steps_run_in_order(self, tmp_path: Path):
        _make_python_library(tmp_path)
        with patch("ai_shell.standardize.umbrella._run_gh") as mock_gh:
            mock_gh.return_value = (0, "", "")
            with patch("ai_shell.standardize.umbrella.verify.run") as mock_v:
                mock_v.return_value = ()
                results = run_all(tmp_path)
        step_names = [r.step for r in results]
        # First 6 steps (detect, dotfiles, precommit, pipeline, renovate, release)
        assert step_names[:6] == [
            "detect",
            "dotfiles",
            "precommit",
            "pipeline",
            "renovate",
            "release",
        ]

    def test_pipeline_yaml_written_on_disk(self, tmp_path: Path):
        _make_python_library(tmp_path)
        with patch("ai_shell.standardize.umbrella._run_gh") as mock_gh:
            mock_gh.return_value = (0, "", "")
            with patch("ai_shell.standardize.umbrella.verify.run") as mock_v:
                mock_v.return_value = ()
                run_all(tmp_path)
        assert (tmp_path / ".github" / "workflows" / "pipeline.yaml").is_file()
        assert (tmp_path / "renovate.json5").is_file()
        assert (tmp_path / ".pre-commit-config.yaml").is_file()

    def test_rulesets_step_calls_ai_gh_apply(self, tmp_path: Path):
        _make_python_library(tmp_path)
        calls = []

        def fake_run_gh(args, cwd):
            calls.append(args)
            return (0, "", "")

        with patch("ai_shell.standardize.umbrella._run_gh", side_effect=fake_run_gh):
            with patch("ai_shell.standardize.umbrella.verify.run") as mock_v:
                mock_v.return_value = ()
                run_all(tmp_path)
        # One apply for library (single ruleset)
        apply_calls = [c for c in calls if c[:2] == ["rulesets", "apply"]]
        assert len(apply_calls) == 1

    def test_rulesets_step_applies_two_for_iac(self, tmp_path: Path):
        _make_python_library(tmp_path)
        # Mark as iac
        (tmp_path / "samconfig.toml").write_text("", encoding="utf-8")
        calls = []

        def fake_run_gh(args, cwd):
            calls.append(args)
            return (0, "", "")

        with patch("ai_shell.standardize.umbrella._run_gh", side_effect=fake_run_gh):
            with patch("ai_shell.standardize.umbrella.verify.run") as mock_v:
                mock_v.return_value = ()
                run_all(tmp_path)
        apply_calls = [c for c in calls if c[:2] == ["rulesets", "apply"]]
        # iac => iac_dev + iac_production
        assert len(apply_calls) == 2

    def test_verify_step_reports_drift(self, tmp_path: Path):
        from ai_shell.standardize.verify import VerifyFinding, VerifyStatus

        _make_python_library(tmp_path)
        drift_finding = VerifyFinding(
            section="pipeline", status=VerifyStatus.DRIFT, message="differs"
        )
        with patch("ai_shell.standardize.umbrella._run_gh") as mock_gh:
            mock_gh.return_value = (0, "", "")
            with patch("ai_shell.standardize.umbrella.verify.run") as mock_v:
                mock_v.return_value = (drift_finding,)
                results = run_all(tmp_path)
        verify_step = next(r for r in results if r.step == "verify")
        assert verify_step.status == StepStatus.FAILED
        assert "1 section(s) drifted" in verify_step.message


class TestAmbiguousLanguageAborts:
    def test_halts_at_detect_step(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
        (tmp_path / "package.json").write_text('{"name":"x"}', encoding="utf-8")
        results = run_all(tmp_path)
        assert len(results) == 1
        assert results[0].step == "detect"
        assert results[0].status == StepStatus.FAILED
        assert "ambiguous" in results[0].message
