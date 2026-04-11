"""Tests for ai_shell.standardize.gates (canonical vocabulary loader)."""

from __future__ import annotations

from ai_shell.standardize.gates import (
    STALE_GATE_NAMES,
    CommitScheme,
    Gates,
    load_commit_scheme,
    load_gates,
)


class TestLoadGates:
    def test_returns_gates_dataclass(self):
        gates = load_gates()
        assert isinstance(gates, Gates)

    def test_canonical_pre_merge_vocabulary(self):
        gates = load_gates()
        assert gates.pre_merge == (
            "Code quality",
            "Security",
            "Unit tests",
            "Compliance",
            "Build validation",
        )

    def test_canonical_post_deploy_vocabulary(self):
        gates = load_gates()
        assert gates.post_deploy == ("Acceptance tests",)

    def test_all_names_concatenates_pre_and_post(self):
        gates = load_gates()
        assert gates.all_names() == gates.pre_merge + gates.post_deploy

    def test_loader_is_cached(self):
        # Two calls should return the same object (lru_cache).
        assert load_gates() is load_gates()


class TestLoadCommitScheme:
    def test_returns_commit_scheme_dataclass(self):
        scheme = load_commit_scheme()
        assert isinstance(scheme, CommitScheme)

    def test_patch_triggers_include_fix_deps(self):
        scheme = load_commit_scheme()
        assert "fix(deps):" in scheme.patch_triggers

    def test_no_release_includes_chore_and_ci(self):
        scheme = load_commit_scheme()
        assert "chore(deps):" in scheme.no_release
        assert "ci(deps):" in scheme.no_release
        assert "docs" in scheme.no_release


class TestStaleGateNames:
    def test_includes_known_drifted_variants(self):
        assert "Pre-commit checks" in STALE_GATE_NAMES
        assert "Security scanning" in STALE_GATE_NAMES
        assert "License compliance" in STALE_GATE_NAMES
        assert "SAST scanning" in STALE_GATE_NAMES

    def test_canonical_names_are_not_in_stale_list(self):
        gates = load_gates()
        for canonical in gates.all_names():
            assert canonical not in STALE_GATE_NAMES
