"""Tests for ai_shell.standardize.dotfiles (T8-2).

`.editorconfig` is an idempotent full-file write; `.gitignore` is an
append-only merge. Both paths must be idempotent on re-run and must not
touch disk when ``dry_run=True``.
"""

from __future__ import annotations

from pathlib import Path

from ai_shell.standardize.dotfiles import (
    _canonical_gitignore_missing,
    _load_editorconfig,
    _load_gitignore,
    apply,
)


class TestEditorconfig:
    def test_writes_canonical_when_absent(self, tmp_path: Path):
        result = apply(tmp_path)
        target = tmp_path / ".editorconfig"
        assert target.is_file()
        assert result.editorconfig_written is True
        assert target.read_text(encoding="utf-8") == _load_editorconfig()

    def test_is_idempotent(self, tmp_path: Path):
        apply(tmp_path)
        result = apply(tmp_path)
        assert result.editorconfig_written is False

    def test_overwrites_drifted_content(self, tmp_path: Path):
        (tmp_path / ".editorconfig").write_text("root = false\n", encoding="utf-8")
        result = apply(tmp_path)
        assert result.editorconfig_written is True
        assert (tmp_path / ".editorconfig").read_text(encoding="utf-8") == _load_editorconfig()

    def test_dry_run_does_not_write(self, tmp_path: Path):
        result = apply(tmp_path, dry_run=True)
        assert not (tmp_path / ".editorconfig").exists()
        assert result.editorconfig_written is True  # planned change, not a disk state


class TestGitignore:
    def test_writes_canonical_when_absent(self, tmp_path: Path):
        result = apply(tmp_path)
        target = tmp_path / ".gitignore"
        assert target.is_file()
        assert result.gitignore_written is True
        # Every canonical entry is present
        content = target.read_text(encoding="utf-8")
        canonical = _load_gitignore()
        for raw in canonical.splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            assert stripped in content

    def test_preserves_existing_custom_entries(self, tmp_path: Path):
        existing = "# my custom header\nlocal-data/\nfixtures/generated/\n"
        (tmp_path / ".gitignore").write_text(existing, encoding="utf-8")
        apply(tmp_path)
        content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        assert "local-data/" in content
        assert "fixtures/generated/" in content
        assert "my custom header" in content
        # Canonical entries are appended
        assert "__pycache__/" in content

    def test_is_idempotent(self, tmp_path: Path):
        apply(tmp_path)
        first = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        result = apply(tmp_path)
        second = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        assert first == second
        assert result.gitignore_written is False
        assert result.gitignore_lines_added == 0

    def test_append_uses_header_marker(self, tmp_path: Path):
        (tmp_path / ".gitignore").write_text("custom-dir/\n", encoding="utf-8")
        apply(tmp_path)
        content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        assert "ai-shell standardize dotfiles" in content
        # Custom entry still present, canonical appended after
        assert content.index("custom-dir/") < content.index("ai-shell standardize dotfiles")

    def test_dry_run_does_not_write(self, tmp_path: Path):
        result = apply(tmp_path, dry_run=True)
        assert not (tmp_path / ".gitignore").exists()
        assert result.gitignore_written is True

    def test_partial_existing_only_appends_missing(self, tmp_path: Path):
        (tmp_path / ".gitignore").write_text(
            "# pre-existing\n__pycache__/\n*.pyc\n", encoding="utf-8"
        )
        result = apply(tmp_path)
        content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        # Canonical entry we already had is not duplicated
        assert content.count("__pycache__/") == 1
        # Something we didn't have got added
        assert ".venv/" in content
        assert result.gitignore_lines_added > 0


class TestCanonicalGitignoreMissing:
    def test_empty_input_returns_all_canonical(self):
        missing = _canonical_gitignore_missing("")
        # Every real canonical entry shows up
        real_missing = [ln for ln in missing if ln.strip() and not ln.strip().startswith("#")]
        canonical_real = [
            ln
            for ln in _load_gitignore().splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        assert len(real_missing) == len(canonical_real)

    def test_fully_present_returns_empty(self):
        canonical = _load_gitignore()
        missing = _canonical_gitignore_missing(canonical)
        real_missing = [ln for ln in missing if ln.strip() and not ln.strip().startswith("#")]
        assert real_missing == []

    def test_empty_group_headers_dropped(self):
        # Feed existing content that covers the entire Python group so the
        # "# === Python ===" header shouldn't appear in the missing output.
        canonical = _load_gitignore()
        py_lines = []
        in_py = False
        for raw in canonical.splitlines():
            if raw.strip() == "# === Python ===":
                in_py = True
                continue
            if in_py and raw.strip().startswith("# ==="):
                break
            if in_py and raw.strip() and not raw.strip().startswith("#"):
                py_lines.append(raw)
        existing = "\n".join(py_lines) + "\n"
        missing = _canonical_gitignore_missing(existing)
        # Python header shouldn't appear alone
        assert "# === Python ===" not in missing
