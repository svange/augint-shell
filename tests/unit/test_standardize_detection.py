"""Tests for ai_shell.standardize.detection."""

from __future__ import annotations

from pathlib import Path

from ai_shell.standardize.detection import Language, RepoType, detect


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestLanguageDetection:
    def test_python_library_from_pyproject(self, tmp_path: Path):
        _write(
            tmp_path / "pyproject.toml",
            '[project]\nname = "x"\nversion = "0.0.0"\n',
        )
        d = detect(tmp_path)
        assert d.language == Language.PYTHON
        assert "pyproject.toml" in d.language_evidence

    def test_python_excluded_when_uv_package_false(self, tmp_path: Path):
        _write(
            tmp_path / "pyproject.toml",
            '[project]\nname = "x"\n[tool.uv]\npackage = false\n',
        )
        d = detect(tmp_path)
        assert d.language == Language.UNKNOWN

    def test_node_from_package_json(self, tmp_path: Path):
        _write(tmp_path / "package.json", '{"name": "x"}')
        d = detect(tmp_path)
        assert d.language == Language.NODE
        assert "package.json" in d.language_evidence

    def test_ambiguous_when_both_present(self, tmp_path: Path):
        _write(
            tmp_path / "pyproject.toml",
            '[project]\nname = "x"\n',
        )
        _write(tmp_path / "package.json", '{"name": "x"}')
        d = detect(tmp_path)
        assert d.language == Language.AMBIGUOUS
        assert d.is_ambiguous()

    def test_unknown_when_nothing(self, tmp_path: Path):
        d = detect(tmp_path)
        assert d.language == Language.UNKNOWN


class TestRepoTypeDetection:
    def test_samconfig_marks_iac(self, tmp_path: Path):
        _write(tmp_path / "pyproject.toml", '[project]\nname = "x"\n')
        _write(tmp_path / "samconfig.toml", "")
        d = detect(tmp_path)
        assert d.repo_type == RepoType.IAC
        assert "samconfig.toml" in d.repo_type_evidence

    def test_cdk_json_marks_iac(self, tmp_path: Path):
        _write(tmp_path / "pyproject.toml", '[project]\nname = "x"\n')
        _write(tmp_path / "cdk.json", "{}")
        d = detect(tmp_path)
        assert d.repo_type == RepoType.IAC
        assert "cdk.json" in d.repo_type_evidence

    def test_terraform_marks_iac(self, tmp_path: Path):
        _write(tmp_path / "pyproject.toml", '[project]\nname = "x"\n')
        _write(tmp_path / "main.tf", "")
        d = detect(tmp_path)
        assert d.repo_type == RepoType.IAC

    def test_library_when_no_deploy_markers(self, tmp_path: Path):
        _write(tmp_path / "pyproject.toml", '[project]\nname = "x"\n')
        d = detect(tmp_path)
        assert d.repo_type == RepoType.LIBRARY

    def test_vite_alone_is_library(self, tmp_path: Path):
        # Vite config without a deploy workflow stays as library
        _write(tmp_path / "package.json", '{"name": "x"}')
        _write(tmp_path / "vite.config.ts", "")
        d = detect(tmp_path)
        assert d.repo_type == RepoType.LIBRARY

    def test_vite_with_deploy_workflow_is_iac(self, tmp_path: Path):
        _write(tmp_path / "package.json", '{"name": "x"}')
        _write(tmp_path / "vite.config.ts", "")
        _write(
            tmp_path / ".github" / "workflows" / "deploy.yml",
            "jobs:\n  deploy:\n    steps:\n      - uses: aws-actions/configure-aws-credentials@v4\n",
        )
        d = detect(tmp_path)
        assert d.repo_type == RepoType.IAC


class TestPublishWinsOverDeploy:
    """Regression tests for T5-1.

    A Python library that uses SAM ``template.yaml`` for ephemeral test
    infrastructure and publishes via ``pypa/gh-action-pypi-publish`` must
    classify as library, not iac.
    """

    def test_template_yaml_alone_is_library(self, tmp_path: Path):
        # template.yaml is NOT a deploy marker on its own. Libraries use it
        # for ephemeral test infra (e.g. ai-lls-lib).
        _write(tmp_path / "pyproject.toml", '[project]\nname = "x"\n')
        _write(tmp_path / "template.yaml", "AWSTemplateFormatVersion: '2010-09-09'\n")
        d = detect(tmp_path)
        assert d.repo_type == RepoType.LIBRARY

    def test_template_yaml_plus_publish_workflow_is_library(self, tmp_path: Path):
        _write(tmp_path / "pyproject.toml", '[project]\nname = "x"\n')
        _write(tmp_path / "template.yaml", "AWSTemplateFormatVersion: '2010-09-09'\n")
        _write(
            tmp_path / ".github" / "workflows" / "pipeline.yaml",
            "jobs:\n  publish:\n    steps:\n      - uses: pypa/gh-action-pypi-publish@v1\n",
        )
        d = detect(tmp_path)
        assert d.repo_type == RepoType.LIBRARY
        assert "pypa/gh-action-pypi-publish" in d.repo_type_evidence

    def test_template_yaml_plus_sam_deploy_workflow_is_iac(self, tmp_path: Path):
        # ai-lls-api pattern: template.yaml, no samconfig.toml, workflow runs `sam deploy`.
        _write(tmp_path / "pyproject.toml", '[project]\nname = "x"\n')
        _write(tmp_path / "template.yaml", "AWSTemplateFormatVersion: '2010-09-09'\n")
        _write(
            tmp_path / ".github" / "workflows" / "ci.yml",
            "jobs:\n  deploy:\n    steps:\n      - run: sam deploy --no-confirm-changeset\n",
        )
        d = detect(tmp_path)
        assert d.repo_type == RepoType.IAC
        assert "sam deploy" in d.repo_type_evidence

    def test_publish_wins_over_sam_deploy(self, tmp_path: Path):
        """A repo that publishes to PyPI and also deploys test infra => library."""
        _write(tmp_path / "pyproject.toml", '[project]\nname = "x"\n')
        _write(tmp_path / "template.yaml", "AWSTemplateFormatVersion: '2010-09-09'\n")
        _write(
            tmp_path / ".github" / "workflows" / "pipeline.yaml",
            (
                "jobs:\n"
                "  deploy-test-infra:\n"
                "    steps:\n"
                "      - run: sam deploy --no-confirm-changeset\n"
                "  publish:\n"
                "    steps:\n"
                "      - uses: pypa/gh-action-pypi-publish@v1\n"
            ),
        )
        d = detect(tmp_path)
        assert d.repo_type == RepoType.LIBRARY

    def test_cdk_json_alone_still_is_iac(self, tmp_path: Path):
        """No publish signal, real deploy marker on disk => iac."""
        _write(tmp_path / "pyproject.toml", '[project]\nname = "x"\n')
        _write(tmp_path / "cdk.json", "{}")
        d = detect(tmp_path)
        assert d.repo_type == RepoType.IAC

    def test_aws_s3_sync_marks_iac(self, tmp_path: Path):
        """Node web app that deploys to S3 but has no samconfig.toml."""
        _write(tmp_path / "package.json", '{"name": "x"}')
        _write(tmp_path / "vite.config.ts", "")
        _write(
            tmp_path / ".github" / "workflows" / "deploy.yml",
            "jobs:\n  deploy:\n    steps:\n      - run: aws s3 sync dist/ s3://bucket/\n",
        )
        d = detect(tmp_path)
        assert d.repo_type == RepoType.IAC
        assert "aws s3 sync" in d.repo_type_evidence

    def test_npm_publish_is_library(self, tmp_path: Path):
        _write(tmp_path / "package.json", '{"name": "x"}')
        _write(
            tmp_path / ".github" / "workflows" / "pipeline.yaml",
            "jobs:\n  publish:\n    steps:\n      - run: npm publish\n",
        )
        d = detect(tmp_path)
        assert d.repo_type == RepoType.LIBRARY
        assert "npm publish" in d.repo_type_evidence
