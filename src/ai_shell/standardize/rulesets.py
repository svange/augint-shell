"""GitHub ruleset spec generator.

Emits one or two ruleset spec JSON files from ``gates.json`` plus the
detected repo type. The umbrella writes each spec to a temp file and calls
``ai-gh rulesets apply <tempfile>`` to mutate GitHub state.

Shapes:

- **library** => one spec (``library`` ruleset on ``~DEFAULT_BRANCH``) with
  the 5 pre-merge gates as required contexts.
- **service** => two specs:
  - ``service_dev`` on ``refs/heads/dev`` with the 5 pre-merge gates only.
  - ``service_production`` on ``~DEFAULT_BRANCH`` with the 5 pre-merge gates +
    ``Acceptance tests``.

Both enforce ``deletion``, ``non_fast_forward``, and
``required_status_checks``. Bypass actors come from
``ruleset-bypass-actors.json`` in the ``ai-standardize-repo`` skill
directory.

The spec shape matches the GitHub REST API request body for
``POST /repos/{owner}/{repo}/rulesets``.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from ai_shell.standardize.detection import Detection, RepoType
from ai_shell.standardize.gates import load_gates

_BYPASS_ACTORS_RESOURCE = (
    "claude",
    "skills",
    "ai-standardize-repo",
    "ruleset-bypass-actors.json",
)


@dataclass(frozen=True)
class RulesetSpec:
    """A single ruleset spec ready to hand to `ai-gh rulesets apply`."""

    name: str
    includes: tuple[str, ...]
    required_contexts: tuple[str, ...]
    body: dict[str, Any]
    temp_path: Path


def _load_bypass_actors() -> list[dict[str, Any]]:
    ref = resources.files("ai_shell.templates").joinpath(*_BYPASS_ACTORS_RESOURCE)
    data: list[dict[str, Any]] = json.loads(ref.read_text(encoding="utf-8"))
    return data


def _build_spec_body(
    name: str,
    includes: tuple[str, ...],
    required_contexts: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "name": name,
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": _load_bypass_actors(),
        "conditions": {
            "ref_name": {"include": list(includes), "exclude": []},
        },
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": False,
                    "required_status_checks": [
                        {"context": context} for context in required_contexts
                    ],
                },
            },
        ],
    }


def _write_temp(name: str, body: dict[str, Any]) -> Path:
    tmp = Path(
        tempfile.NamedTemporaryFile(
            prefix=f"ruleset-{name}-",
            suffix=".json",
            delete=False,
        ).name
    )
    tmp.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return tmp


def generate(detection: Detection) -> tuple[RulesetSpec, ...]:
    """Generate the ruleset spec(s) for *detection*.

    Returns one spec for library repos, two for service repos.
    """
    gates = load_gates()
    pre_merge = gates.pre_merge
    post_deploy = gates.post_deploy

    if detection.repo_type == RepoType.LIBRARY:
        body = _build_spec_body(
            "library",
            includes=("~DEFAULT_BRANCH",),
            required_contexts=pre_merge,
        )
        return (
            RulesetSpec(
                name="library",
                includes=("~DEFAULT_BRANCH",),
                required_contexts=pre_merge,
                body=body,
                temp_path=_write_temp("library", body),
            ),
        )

    # service: two rulesets
    dev_body = _build_spec_body(
        "service_dev",
        includes=("refs/heads/dev",),
        required_contexts=pre_merge,
    )
    prod_contexts = pre_merge + post_deploy
    prod_body = _build_spec_body(
        "service_production",
        includes=("~DEFAULT_BRANCH",),
        required_contexts=prod_contexts,
    )
    return (
        RulesetSpec(
            name="service_dev",
            includes=("refs/heads/dev",),
            required_contexts=pre_merge,
            body=dev_body,
            temp_path=_write_temp("service-dev", dev_body),
        ),
        RulesetSpec(
            name="service_production",
            includes=("~DEFAULT_BRANCH",),
            required_contexts=prod_contexts,
            body=prod_body,
            temp_path=_write_temp("service-production", prod_body),
        ),
    )
