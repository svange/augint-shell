"""Tests for ai_shell.standardize.verify PyGithub-backed checks (T5-2)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ai_shell.standardize.detection import Detection, Language, RepoType
from ai_shell.standardize.verify import (
    VerifyStatus,
    _load_gh_env,
    _verify_repo_settings,
    _verify_rulesets,
)


def _det_library() -> Detection:
    return Detection(
        language=Language.PYTHON,
        repo_type=RepoType.LIBRARY,
        language_evidence=(),
        repo_type_evidence=(),
    )


def _det_iac() -> Detection:
    return Detection(
        language=Language.PYTHON,
        repo_type=RepoType.IAC,
        language_evidence=(),
        repo_type_evidence=(),
    )


def _mock_repo_with_rulesets(live_rulesets: list[dict]) -> MagicMock:
    """Build a PyGithub Repository mock whose `_requester` returns *live_rulesets*.

    `requestJsonAndCheck` is called twice per ruleset: once for the list
    (returning summaries) and once for each detail. We implement both via a
    side_effect that walks the call sequence.
    """
    repo = MagicMock()
    repo.url = "https://api.github.com/repos/owner/name"
    summaries = [{"id": i, "name": rs["name"]} for i, rs in enumerate(live_rulesets)]
    details_by_id = dict(enumerate(live_rulesets))

    def fake_request(method: str, url: str, **_kw):
        if url.endswith("/rulesets"):
            return ({}, summaries)
        # /rulesets/{id}
        rs_id = int(url.rsplit("/", 1)[-1])
        return ({}, details_by_id[rs_id])

    repo._requester.requestJsonAndCheck.side_effect = fake_request
    return repo


def _mock_repo_with_settings(**overrides) -> MagicMock:
    defaults = {
        "allow_merge_commit": True,
        "allow_squash_merge": False,
        "allow_rebase_merge": False,
        "allow_auto_merge": True,
        "merge_commit_title": "PR_TITLE",
        "merge_commit_message": "PR_BODY",
        "delete_branch_on_merge": True,
    }
    defaults.update(overrides)
    repo = SimpleNamespace(**defaults)
    return repo


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch):
    for key in ("GH_REPO", "GH_ACCOUNT", "GH_TOKEN"):
        monkeypatch.delenv(key, raising=False)


class TestLoadGhEnv:
    def test_returns_none_when_missing(self, tmp_path: Path, clean_env):
        assert _load_gh_env(tmp_path) is None

    def test_loads_from_env_file(self, tmp_path: Path, clean_env):
        (tmp_path / ".env").write_text(
            "GH_REPO=name\nGH_ACCOUNT=owner\nGH_TOKEN=tok\n", encoding="utf-8"
        )
        env = _load_gh_env(tmp_path)
        assert env == ("name", "owner", "tok")

    def test_env_vars_win_when_already_set(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("GH_REPO", "envrepo")
        monkeypatch.setenv("GH_ACCOUNT", "envowner")
        monkeypatch.setenv("GH_TOKEN", "envtok")
        (tmp_path / ".env").write_text(
            "GH_REPO=filerepo\nGH_ACCOUNT=fileowner\nGH_TOKEN=filetok\n",
            encoding="utf-8",
        )
        # load_dotenv is called with override=False, so os.environ wins
        env = _load_gh_env(tmp_path)
        assert env == ("envrepo", "envowner", "envtok")


class TestVerifyRulesets:
    def test_fail_when_env_missing(self, tmp_path: Path, clean_env):
        finding = _verify_rulesets(tmp_path, _det_library())
        assert finding.status == VerifyStatus.FAIL
        assert "GH_REPO" in finding.message

    def test_pass_when_library_ruleset_matches(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("GH_REPO", "x")
        monkeypatch.setenv("GH_ACCOUNT", "y")
        monkeypatch.setenv("GH_TOKEN", "z")
        live = [
            {
                "name": "library",
                "rules": [
                    {
                        "type": "required_status_checks",
                        "parameters": {
                            "required_status_checks": [
                                {"context": "Code quality"},
                                {"context": "Security"},
                                {"context": "Unit tests"},
                                {"context": "Compliance"},
                                {"context": "Build validation"},
                            ]
                        },
                    }
                ],
            }
        ]
        repo = _mock_repo_with_rulesets(live)
        with patch("ai_shell.standardize.verify._open_github_repo", return_value=repo):
            finding = _verify_rulesets(tmp_path, _det_library())
        assert finding.status == VerifyStatus.PASS

    def test_drift_when_ruleset_missing(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("GH_REPO", "x")
        monkeypatch.setenv("GH_ACCOUNT", "y")
        monkeypatch.setenv("GH_TOKEN", "z")
        repo = _mock_repo_with_rulesets([])  # no live rulesets
        with patch("ai_shell.standardize.verify._open_github_repo", return_value=repo):
            finding = _verify_rulesets(tmp_path, _det_library())
        assert finding.status == VerifyStatus.DRIFT
        assert "missing rulesets" in finding.message
        assert "library" in finding.message

    def test_drift_when_context_missing_on_live_ruleset(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("GH_REPO", "x")
        monkeypatch.setenv("GH_ACCOUNT", "y")
        monkeypatch.setenv("GH_TOKEN", "z")
        # library ruleset exists but is missing `Compliance`
        live = [
            {
                "name": "library",
                "rules": [
                    {
                        "type": "required_status_checks",
                        "parameters": {
                            "required_status_checks": [
                                {"context": "Code quality"},
                                {"context": "Security"},
                                {"context": "Unit tests"},
                                {"context": "Build validation"},
                            ]
                        },
                    }
                ],
            }
        ]
        repo = _mock_repo_with_rulesets(live)
        with patch("ai_shell.standardize.verify._open_github_repo", return_value=repo):
            finding = _verify_rulesets(tmp_path, _det_library())
        assert finding.status == VerifyStatus.DRIFT
        assert "missing contexts: Compliance" in finding.message

    def test_iac_requires_two_rulesets(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("GH_REPO", "x")
        monkeypatch.setenv("GH_ACCOUNT", "y")
        monkeypatch.setenv("GH_TOKEN", "z")
        # Only iac_dev exists, iac_production missing
        live = [
            {
                "name": "iac_dev",
                "rules": [
                    {
                        "type": "required_status_checks",
                        "parameters": {
                            "required_status_checks": [
                                {"context": "Code quality"},
                                {"context": "Security"},
                                {"context": "Unit tests"},
                                {"context": "Compliance"},
                                {"context": "Build validation"},
                            ]
                        },
                    }
                ],
            }
        ]
        repo = _mock_repo_with_rulesets(live)
        with patch("ai_shell.standardize.verify._open_github_repo", return_value=repo):
            finding = _verify_rulesets(tmp_path, _det_iac())
        assert finding.status == VerifyStatus.DRIFT
        assert "iac_production" in finding.message

    def test_github_api_error_is_fail(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("GH_REPO", "x")
        monkeypatch.setenv("GH_ACCOUNT", "y")
        monkeypatch.setenv("GH_TOKEN", "z")
        with patch(
            "ai_shell.standardize.verify._open_github_repo",
            side_effect=RuntimeError("404 Not Found"),
        ):
            finding = _verify_rulesets(tmp_path, _det_library())
        assert finding.status == VerifyStatus.FAIL
        assert "404" in finding.message


class TestVerifyRepoSettings:
    def test_fail_when_env_missing(self, tmp_path: Path, clean_env):
        finding = _verify_repo_settings(tmp_path)
        assert finding.status == VerifyStatus.FAIL
        assert "GH_REPO" in finding.message

    def test_pass_when_all_settings_match_contract(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("GH_REPO", "x")
        monkeypatch.setenv("GH_ACCOUNT", "y")
        monkeypatch.setenv("GH_TOKEN", "z")
        repo = _mock_repo_with_settings()
        with patch("ai_shell.standardize.verify._open_github_repo", return_value=repo):
            finding = _verify_repo_settings(tmp_path)
        assert finding.status == VerifyStatus.PASS

    def test_drift_when_squash_allowed(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("GH_REPO", "x")
        monkeypatch.setenv("GH_ACCOUNT", "y")
        monkeypatch.setenv("GH_TOKEN", "z")
        repo = _mock_repo_with_settings(allow_squash_merge=True)
        with patch("ai_shell.standardize.verify._open_github_repo", return_value=repo):
            finding = _verify_repo_settings(tmp_path)
        assert finding.status == VerifyStatus.DRIFT
        assert "allow_squash_merge" in finding.message

    def test_drift_when_merge_title_wrong(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("GH_REPO", "x")
        monkeypatch.setenv("GH_ACCOUNT", "y")
        monkeypatch.setenv("GH_TOKEN", "z")
        repo = _mock_repo_with_settings(merge_commit_title="MERGE_MESSAGE")
        with patch("ai_shell.standardize.verify._open_github_repo", return_value=repo):
            finding = _verify_repo_settings(tmp_path)
        assert finding.status == VerifyStatus.DRIFT
        assert "merge_commit_title" in finding.message

    def test_does_not_shell_out_to_ai_gh(self, tmp_path: Path, monkeypatch):
        """Regression for T5-2: must not invoke ai-gh subprocess at all."""
        monkeypatch.setenv("GH_REPO", "x")
        monkeypatch.setenv("GH_ACCOUNT", "y")
        monkeypatch.setenv("GH_TOKEN", "z")
        repo = _mock_repo_with_settings()
        with patch("subprocess.run") as mock_run:
            with patch("ai_shell.standardize.verify._open_github_repo", return_value=repo):
                _verify_repo_settings(tmp_path)
        mock_run.assert_not_called()
