"""Tests for `ai-shell standardize` CLI command wiring.

These tests target the CLI layer only: JSON output shape, exit codes,
flag plumbing. Core generator / validator logic is tested in the
per-module test files.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from ai_shell.cli.__main__ import cli
from ai_shell.standardize.pipeline import DriftReport
from ai_shell.standardize.verify import VerifyFinding, VerifyStatus


class TestVerifyJson:
    """T8-3: `standardize repo --verify --json` must emit structured JSON."""

    def setup_method(self):
        self.runner = CliRunner()

    def _fake_findings_clean(self) -> tuple[VerifyFinding, ...]:
        return (
            VerifyFinding(section="detect", status=VerifyStatus.PASS, message="python/library"),
            VerifyFinding(
                section="pipeline", status=VerifyStatus.PASS, message="all gates present"
            ),
        )

    def _fake_findings_drift(self) -> tuple[VerifyFinding, ...]:
        return (
            VerifyFinding(section="detect", status=VerifyStatus.PASS, message="python/library"),
            VerifyFinding(
                section="pipeline",
                status=VerifyStatus.DRIFT,
                message="missing: Security",
                diff="--- a\n+++ b\n",
            ),
        )

    def test_verify_json_clean_emits_json_and_exit_zero(self, tmp_path: Path):
        with patch("ai_shell.cli.commands.standardize._verify_run") as mock_v:
            mock_v.return_value = self._fake_findings_clean()
            result = self.runner.invoke(
                cli, ["standardize", "repo", "--verify", "--json", str(tmp_path)]
            )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["overall"] == "clean"
        assert payload["path"] == str(tmp_path.resolve())
        assert len(payload["findings"]) == 2
        assert payload["findings"][0]["section"] == "detect"
        assert payload["findings"][0]["status"] == "PASS"
        assert payload["findings"][0]["is_clean"] is True

    def test_verify_json_drift_emits_json_and_exit_one(self, tmp_path: Path):
        with patch("ai_shell.cli.commands.standardize._verify_run") as mock_v:
            mock_v.return_value = self._fake_findings_drift()
            result = self.runner.invoke(
                cli, ["standardize", "repo", "--verify", "--json", str(tmp_path)]
            )
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["overall"] == "drift"
        drift_entry = next(f for f in payload["findings"] if f["section"] == "pipeline")
        assert drift_entry["status"] == "DRIFT"
        assert drift_entry["is_clean"] is False
        assert drift_entry["diff"] == "--- a\n+++ b\n"

    def test_verify_without_json_still_prints_text(self, tmp_path: Path):
        with patch("ai_shell.cli.commands.standardize._verify_run") as mock_v:
            mock_v.return_value = self._fake_findings_clean()
            result = self.runner.invoke(cli, ["standardize", "repo", "--verify", str(tmp_path)])
        assert result.exit_code == 0
        # Rich output with bracketed status tags
        assert "PASS" in result.output
        assert "python/library" in result.output


class TestPipelineValidateSpecHint:
    """T8-4: `pipeline --validate` must hint at `--print-template` on spec
    failures so the user can diff the canonical body without grepping."""

    def setup_method(self):
        self.runner = CliRunner()

    def test_spec_failure_emits_print_template_hint(self, tmp_path: Path):
        # Make tmp_path look like a python library so detection resolves.
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "0.0.0"\n', encoding="utf-8"
        )
        report = DriftReport(
            pipeline_path=tmp_path / ".github/workflows/pipeline.yaml",
            pipeline_present=True,
            present=("Security",),
            missing=(),
            legacy_candidates=(),
            custom_jobs=(),
            spec_failures=(("Security", "missing required action step: semgrep/semgrep-action"),),
        )
        with patch("ai_shell.cli.commands.standardize.validate") as mock_validate:
            mock_validate.return_value = report
            result = self.runner.invoke(
                cli, ["standardize", "pipeline", "--validate", str(tmp_path)]
            )
        assert result.exit_code == 1
        # Collapse Rich's line-wrapping so assertions can match the
        # logical command string regardless of console width.
        flat = " ".join(result.output.split())
        assert "spec failures" in flat
        assert "Security:" in flat
        # The hint points the user at --print-template with the exact gate
        # and resolved language/type so they don't have to look anything up.
        assert "--print-template 'Security'" in flat
        assert "--language python" in flat
        assert "--type library" in flat
