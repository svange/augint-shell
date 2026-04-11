"""Tests for ai_shell.standardize.rulesets spec generator."""

from __future__ import annotations

import json

from ai_shell.standardize.detection import Detection, Language, RepoType
from ai_shell.standardize.gates import load_gates
from ai_shell.standardize.rulesets import generate


def _det(typ: RepoType) -> Detection:
    return Detection(
        language=Language.PYTHON,
        repo_type=typ,
        language_evidence=(),
        repo_type_evidence=(),
    )


class TestLibrarySpec:
    def test_emits_single_spec(self):
        specs = generate(_det(RepoType.LIBRARY))
        assert len(specs) == 1

    def test_name_is_library(self):
        specs = generate(_det(RepoType.LIBRARY))
        assert specs[0].name == "library"

    def test_targets_default_branch(self):
        specs = generate(_det(RepoType.LIBRARY))
        assert specs[0].includes == ("~DEFAULT_BRANCH",)

    def test_required_contexts_are_5_pre_merge_gates(self):
        specs = generate(_det(RepoType.LIBRARY))
        gates = load_gates()
        assert set(specs[0].required_contexts) == set(gates.pre_merge)
        assert "Acceptance tests" not in specs[0].required_contexts

    def test_body_contains_deletion_and_non_fast_forward(self):
        specs = generate(_det(RepoType.LIBRARY))
        rule_types = {r["type"] for r in specs[0].body["rules"]}
        assert "deletion" in rule_types
        assert "non_fast_forward" in rule_types
        assert "required_status_checks" in rule_types


class TestIacSpecs:
    def test_emits_two_specs(self):
        specs = generate(_det(RepoType.IAC))
        assert len(specs) == 2

    def test_dev_and_production_names(self):
        specs = generate(_det(RepoType.IAC))
        names = {s.name for s in specs}
        assert names == {"iac_dev", "iac_production"}

    def test_dev_targets_dev_branch(self):
        specs = generate(_det(RepoType.IAC))
        dev = next(s for s in specs if s.name == "iac_dev")
        assert dev.includes == ("refs/heads/dev",)

    def test_production_targets_default_branch(self):
        specs = generate(_det(RepoType.IAC))
        prod = next(s for s in specs if s.name == "iac_production")
        assert prod.includes == ("~DEFAULT_BRANCH",)

    def test_dev_has_only_5_pre_merge_gates(self):
        specs = generate(_det(RepoType.IAC))
        dev = next(s for s in specs if s.name == "iac_dev")
        gates = load_gates()
        assert set(dev.required_contexts) == set(gates.pre_merge)
        assert "Acceptance tests" not in dev.required_contexts

    def test_production_has_all_6_gates(self):
        specs = generate(_det(RepoType.IAC))
        prod = next(s for s in specs if s.name == "iac_production")
        gates = load_gates()
        assert set(prod.required_contexts) == set(gates.all_names())
        assert "Acceptance tests" in prod.required_contexts


class TestTempFiles:
    def test_writes_parseable_json_to_temp(self):
        specs = generate(_det(RepoType.LIBRARY))
        for spec in specs:
            assert spec.temp_path.is_file()
            data = json.loads(spec.temp_path.read_text(encoding="utf-8"))
            assert data["name"] == spec.name
            # Clean up
            spec.temp_path.unlink()

    def test_bypass_actors_loaded(self):
        specs = generate(_det(RepoType.LIBRARY))
        body = specs[0].body
        actors = body["bypass_actors"]
        assert isinstance(actors, list)
        assert len(actors) >= 1
        assert all("actor_type" in a for a in actors)
        specs[0].temp_path.unlink()
