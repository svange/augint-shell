"""Tests for ai_shell.standardize.renovate generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_shell.standardize.detection import Detection, Language, RepoType
from ai_shell.standardize.renovate import RenovateAlignmentError, apply


def _det(lang: Language, typ: RepoType) -> Detection:
    return Detection(
        language=lang,
        repo_type=typ,
        language_evidence=(),
        repo_type_evidence=(),
    )


def _strip_jsonc_comments(text: str) -> str:
    """Very naive comment stripper for assert-only parsing in tests.

    json5 is a superset of JSON. Our template only uses `// line comments`,
    never inline `/* */` blocks, so this is enough to feed the result to
    json.loads for shape assertions.
    """
    out_lines = []
    for line in text.splitlines():
        # Drop full-line comments
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue
        # Drop trailing //... comments on the line
        idx = line.find("//")
        if idx != -1:
            # Only if the `//` isn't inside a string literal. Our templates
            # keep // comments on their own lines or after structural
            # tokens, so a simple check suffices.
            before = line[:idx]
            if before.count('"') % 2 == 0:
                line = before.rstrip()
                if not line:
                    continue
        out_lines.append(line)
    text = "\n".join(out_lines)
    # Drop trailing commas (json5 allows them, json doesn't)
    import re

    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return text


class TestApplyEachCombination:
    @pytest.mark.parametrize(
        ("lang", "typ"),
        [
            (Language.PYTHON, RepoType.LIBRARY),
            (Language.PYTHON, RepoType.SERVICE),
            (Language.NODE, RepoType.LIBRARY),
            (Language.NODE, RepoType.SERVICE),
        ],
    )
    def test_writes_file(self, tmp_path: Path, lang: Language, typ: RepoType):
        result = apply(_det(lang, typ), tmp_path)
        assert result.path.is_file()
        assert result.path.name == "renovate.json5"

    def test_python_library_uses_pep621(self, tmp_path: Path):
        result = apply(_det(Language.PYTHON, RepoType.LIBRARY), tmp_path)
        text = result.path.read_text(encoding="utf-8")
        assert '"pep621"' in text
        assert '"project.dependencies"' in text

    def test_node_library_uses_npm(self, tmp_path: Path):
        result = apply(_det(Language.NODE, RepoType.LIBRARY), tmp_path)
        text = result.path.read_text(encoding="utf-8")
        assert '"npm"' in text
        assert '"dependencies"' in text
        assert '"devDependencies"' in text
        assert '"pep621"' not in text
        assert '"project.dependencies"' not in text

    def test_node_service_forces_merge_automerge_strategy(self, tmp_path: Path):
        """node/service MUST use automergeStrategy: merge (never squash)."""
        result = apply(_det(Language.NODE, RepoType.SERVICE), tmp_path)
        text = result.path.read_text(encoding="utf-8")
        parsed = json.loads(_strip_jsonc_comments(text))
        assert parsed.get("automergeStrategy") == "merge"

    def test_service_targets_dev_branch(self, tmp_path: Path):
        result = apply(_det(Language.PYTHON, RepoType.SERVICE), tmp_path)
        text = result.path.read_text(encoding="utf-8")
        parsed = json.loads(_strip_jsonc_comments(text))
        assert parsed.get("baseBranchPatterns") == ["dev"]

    def test_python_package_rule_uses_python_semantic_release(self, tmp_path: Path):
        result = apply(_det(Language.PYTHON, RepoType.LIBRARY), tmp_path)
        parsed = json.loads(_strip_jsonc_comments(result.path.read_text(encoding="utf-8")))
        pkg_names = {
            name
            for rule in parsed.get("packageRules", [])
            for name in rule.get("matchPackageNames", [])
        }
        assert "python-semantic-release" in pkg_names
        assert "semantic-release" not in pkg_names

    def test_node_package_rule_uses_semantic_release(self, tmp_path: Path):
        result = apply(_det(Language.NODE, RepoType.LIBRARY), tmp_path)
        parsed = json.loads(_strip_jsonc_comments(result.path.read_text(encoding="utf-8")))
        pkg_names = {
            name
            for rule in parsed.get("packageRules", [])
            for name in rule.get("matchPackageNames", [])
        }
        assert "semantic-release" in pkg_names
        assert "python-semantic-release" not in pkg_names


class TestNoAdaptProseInOutput:
    """Regression for T5-3: renovate templates must not leak ADAPT prose."""

    @pytest.mark.parametrize(
        ("lang", "typ"),
        [
            (Language.PYTHON, RepoType.LIBRARY),
            (Language.PYTHON, RepoType.SERVICE),
            (Language.NODE, RepoType.LIBRARY),
            (Language.NODE, RepoType.SERVICE),
        ],
    )
    def test_no_adapt_comments_on_disk(self, tmp_path: Path, lang: Language, typ: RepoType):
        result = apply(_det(lang, typ), tmp_path)
        content = result.path.read_text(encoding="utf-8")
        assert "ADAPT before writing" not in content
        assert "ADAPT: " not in content


class TestCrossValidation:
    def test_raises_on_unknown_commit_prefix(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """If the rendered template uses a commit prefix missing from
        commit-scheme.json, the generator must abort."""
        from ai_shell.standardize import renovate as mod

        def fake_template(_name: str) -> str:
            return (
                "{\n"
                '  "enabledManagers": ["pep621"],\n'
                '  "packageRules": [\n'
                '    {"commitMessagePrefix": "wat(deps):"}\n'
                "  ]\n"
                "}\n"
            )

        monkeypatch.setattr(mod, "_load_template", fake_template)
        with pytest.raises(RenovateAlignmentError) as exc:
            apply(_det(Language.PYTHON, RepoType.LIBRARY), tmp_path)
        assert "wat(deps):" in str(exc.value)


class TestAmbiguousRaises:
    def test_ambiguous_language_raises(self, tmp_path: Path):
        det = Detection(
            language=Language.AMBIGUOUS,
            repo_type=RepoType.LIBRARY,
            language_evidence=(),
            repo_type_evidence=(),
        )
        with pytest.raises(ValueError):
            apply(det, tmp_path)
