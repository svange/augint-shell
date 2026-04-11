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

    def test_python_content_files_written_on_disk(self, tmp_path: Path):
        """Renovate + pre-commit are still Python-written; pipeline is now
        AI-mediated (T5-7) and the umbrella only emits a SKIPPED hint."""
        _make_python_library(tmp_path)
        with patch("ai_shell.standardize.umbrella._run_gh") as mock_gh:
            mock_gh.return_value = (0, "", "")
            with patch("ai_shell.standardize.umbrella.verify.run") as mock_v:
                mock_v.return_value = ()
                run_all(tmp_path)
        assert (tmp_path / "renovate.json5").is_file()
        assert (tmp_path / ".pre-commit-config.yaml").is_file()
        # Pipeline.yaml is NOT written by Python under T5-7.
        assert not (tmp_path / ".github" / "workflows" / "pipeline.yaml").is_file()

    def test_pipeline_step_needs_action_when_pipeline_missing(self, tmp_path: Path):
        """T5-7 + T5-12: when pipeline.yaml is absent the umbrella reports
        NEEDS_ACTION (not silent SKIPPED) with a hint to invoke the
        /ai-standardize-pipeline sub-skill."""
        _make_python_library(tmp_path)
        with patch("ai_shell.standardize.umbrella._run_gh") as mock_gh:
            mock_gh.return_value = (0, "", "")
            with patch("ai_shell.standardize.umbrella.verify.run") as mock_v:
                mock_v.return_value = ()
                results = run_all(tmp_path)
        pipeline_step = next(r for r in results if r.step == "pipeline")
        assert pipeline_step.status == StepStatus.NEEDS_ACTION
        assert "ai-standardize-pipeline" in pipeline_step.message

    def test_oidc_step_needs_action_not_skipped(self, tmp_path: Path):
        """T5-12: OIDC must not return a silent SKIPPED. It returns
        NEEDS_ACTION with an actionable message pointing at the sub-skill."""
        _make_python_library(tmp_path)
        with patch("ai_shell.standardize.umbrella._run_gh") as mock_gh:
            mock_gh.return_value = (0, "", "")
            with patch("ai_shell.standardize.umbrella.verify.run") as mock_v:
                mock_v.return_value = ()
                results = run_all(tmp_path)
        oidc_step = next(r for r in results if r.step == "oidc")
        assert oidc_step.status == StepStatus.NEEDS_ACTION
        assert "ai-setup-oidc" in oidc_step.message

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


class TestDryRun:
    """T5-14: `--dry-run` runs every step in compute-but-don't-write mode."""

    def test_dry_run_does_not_write_editorconfig(self, tmp_path: Path):
        _make_python_library(tmp_path)
        with patch("ai_shell.standardize.umbrella._run_gh") as mock_gh:
            mock_gh.return_value = (0, "", "")
            with patch("ai_shell.standardize.umbrella.verify.run") as mock_v:
                mock_v.return_value = ()
                results = run_all(tmp_path, dry_run=True)
        # Python sub-generators are invoked with dry_run=True and write nothing
        assert not (tmp_path / ".editorconfig").exists()
        assert not (tmp_path / ".pre-commit-config.yaml").exists()
        assert not (tmp_path / "renovate.json5").exists()
        # All steps should still run and report OK / NEEDS_ACTION
        step_names = [r.step for r in results]
        assert "dotfiles" in step_names
        assert "precommit" in step_names
        assert "renovate" in step_names
        assert "release" in step_names

    def test_dry_run_chains_ai_gh_dry_run_for_repo_settings(self, tmp_path: Path):
        _make_python_library(tmp_path)
        calls = []

        def fake_run_gh(args, cwd):
            calls.append(args)
            return (0, "", "")

        with patch("ai_shell.standardize.umbrella._run_gh", side_effect=fake_run_gh):
            with patch("ai_shell.standardize.umbrella.verify.run") as mock_v:
                mock_v.return_value = ()
                run_all(tmp_path, dry_run=True)

        config_calls = [c for c in calls if c[:2] == ["config", "--standardize"]]
        assert len(config_calls) == 1
        assert "--dry-run" in config_calls[0]

    def test_dry_run_chains_ai_gh_dry_run_for_rulesets(self, tmp_path: Path):
        _make_python_library(tmp_path)
        calls = []

        def fake_run_gh(args, cwd):
            calls.append(args)
            return (0, "", "")

        with patch("ai_shell.standardize.umbrella._run_gh", side_effect=fake_run_gh):
            with patch("ai_shell.standardize.umbrella.verify.run") as mock_v:
                mock_v.return_value = ()
                run_all(tmp_path, dry_run=True)

        apply_calls = [c for c in calls if c[:2] == ["rulesets", "apply"]]
        assert len(apply_calls) == 1
        assert "--dry-run" in apply_calls[0]

    def test_dry_run_verify_drift_is_not_a_failure(self, tmp_path: Path):
        """Dry-run verify reports the pre-apply baseline; drift is expected
        because nothing has been written yet. It must not be reported as
        FAILED, otherwise the final CLI exit code would be non-zero even
        when the plan is valid."""
        from ai_shell.standardize.verify import VerifyFinding, VerifyStatus

        _make_python_library(tmp_path)
        drift_finding = VerifyFinding(
            section="pipeline", status=VerifyStatus.DRIFT, message="differs"
        )
        with patch("ai_shell.standardize.umbrella._run_gh") as mock_gh:
            mock_gh.return_value = (0, "", "")
            with patch("ai_shell.standardize.umbrella.verify.run") as mock_v:
                mock_v.return_value = (drift_finding,)
                results = run_all(tmp_path, dry_run=True)
        verify_step = next(r for r in results if r.step == "verify")
        assert verify_step.status == StepStatus.OK
        assert "dry-run" in verify_step.message

    def test_dry_run_oidc_still_needs_action(self, tmp_path: Path):
        _make_python_library(tmp_path)
        with patch("ai_shell.standardize.umbrella._run_gh") as mock_gh:
            mock_gh.return_value = (0, "", "")
            with patch("ai_shell.standardize.umbrella.verify.run") as mock_v:
                mock_v.return_value = ()
                results = run_all(tmp_path, dry_run=True)
        oidc_step = next(r for r in results if r.step == "oidc")
        assert oidc_step.status == StepStatus.NEEDS_ACTION
        assert "dry-run" in oidc_step.message

    def test_non_dry_run_still_writes(self, tmp_path: Path):
        """Regression: dry_run defaults to False; the write path still works."""
        _make_python_library(tmp_path)
        with patch("ai_shell.standardize.umbrella._run_gh") as mock_gh:
            mock_gh.return_value = (0, "", "")
            with patch("ai_shell.standardize.umbrella.verify.run") as mock_v:
                mock_v.return_value = ()
                run_all(tmp_path)
        assert (tmp_path / ".editorconfig").is_file()
        assert (tmp_path / ".pre-commit-config.yaml").is_file()
        assert (tmp_path / "renovate.json5").is_file()
