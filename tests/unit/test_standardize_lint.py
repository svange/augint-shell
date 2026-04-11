"""Tests for ai_shell.standardize.lint (drift scanner)."""

from __future__ import annotations

from pathlib import Path

from ai_shell.standardize.lint import scan


class TestScan:
    def test_clean_tree_returns_no_hits(self, tmp_path: Path):
        (tmp_path / "ok.md").write_text("# All canonical: Code quality and Security\n")
        assert scan(tmp_path) == []

    def test_detects_stale_pre_commit_checks(self, tmp_path: Path):
        (tmp_path / "drift.md").write_text("## Pre-commit checks\nsome prose\n")
        hits = scan(tmp_path)
        assert len(hits) == 1
        assert hits[0].match == "Pre-commit checks"
        assert hits[0].line == 1
        assert hits[0].path.name == "drift.md"

    def test_detects_stale_security_scanning_in_yaml(self, tmp_path: Path):
        (tmp_path / "pipeline.yaml").write_text("jobs:\n  scan:\n    name: Security scanning\n")
        hits = scan(tmp_path)
        assert len(hits) == 1
        assert hits[0].match == "Security scanning"
        assert hits[0].line == 3

    def test_ignores_non_text_suffixes(self, tmp_path: Path):
        (tmp_path / "binary.bin").write_text("Pre-commit checks")
        (tmp_path / "script.py").write_text("# Pre-commit checks")
        assert scan(tmp_path) == []

    def test_ignores_venv_and_caches(self, tmp_path: Path):
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "bad.md").write_text("Pre-commit checks")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "bad.md").write_text("Pre-commit checks")
        assert scan(tmp_path) == []

    def test_ignores_nested_woxom_workspace(self, tmp_path: Path):
        nested = tmp_path / "woxom-ecosystem" / "child"
        nested.mkdir(parents=True)
        (nested / "bad.md").write_text("Pre-commit checks")
        assert scan(tmp_path) == []

    def test_format_emits_path_line_and_match(self, tmp_path: Path):
        (tmp_path / "drift.md").write_text("bad: Pre-commit checks here\n")
        hits = scan(tmp_path)
        formatted = hits[0].format(tmp_path)
        assert "drift.md" in formatted
        assert ":1:" in formatted
        assert "Pre-commit checks" in formatted

    def test_multiple_hits_across_files(self, tmp_path: Path):
        (tmp_path / "a.md").write_text("Pre-commit checks\n")
        (tmp_path / "b.yaml").write_text("name: License compliance\n")
        hits = scan(tmp_path)
        assert len(hits) == 2
        matches = {h.match for h in hits}
        assert matches == {"Pre-commit checks", "License compliance"}
