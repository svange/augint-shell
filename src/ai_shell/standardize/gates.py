"""Canonical gate vocabulary loader.

`gates.json` and `commit-scheme.json` live in the `ai-standardize-repo` skill
template directory as the single source of truth for gate names and the
Renovate <-> semantic-release commit-prefix alignment. Every generator in this
package reads from here; no other module is allowed to hardcode gate names.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

_GATES_RESOURCE = ("claude", "skills", "ai-standardize-repo", "gates.json")
_COMMIT_SCHEME_RESOURCE = ("claude", "skills", "ai-standardize-repo", "commit-scheme.json")


@dataclass(frozen=True)
class Gates:
    """Canonical gate vocabulary."""

    pre_merge: tuple[str, ...]
    post_deploy: tuple[str, ...]

    def all_names(self) -> tuple[str, ...]:
        return self.pre_merge + self.post_deploy


@dataclass(frozen=True)
class CommitScheme:
    """Full conventional commit -> release behavior mapping.

    Single source of truth for Renovate commit prefixes and
    semantic-release rules. All four categories must be kept in sync
    with commit-scheme.json.
    """

    major_triggers: tuple[str, ...]
    minor_triggers: tuple[str, ...]
    patch_triggers: tuple[str, ...]
    no_release: tuple[str, ...]


def _load_resource_json(parts: tuple[str, ...]) -> dict[str, Any]:
    ref = resources.files("ai_shell.templates").joinpath(*parts)
    data: dict[str, Any] = json.loads(ref.read_text(encoding="utf-8"))
    return data


@lru_cache(maxsize=1)
def load_gates() -> Gates:
    """Load and cache the canonical gate vocabulary."""
    data = _load_resource_json(_GATES_RESOURCE)
    return Gates(
        pre_merge=tuple(data["pre_merge"]),
        post_deploy=tuple(data["post_deploy"]),
    )


@lru_cache(maxsize=1)
def load_commit_scheme() -> CommitScheme:
    """Load and cache the Renovate/semantic-release commit prefix alignment."""
    data = _load_resource_json(_COMMIT_SCHEME_RESOURCE)
    return CommitScheme(
        major_triggers=tuple(data.get("major_triggers", ())),
        minor_triggers=tuple(data.get("minor_triggers", ())),
        patch_triggers=tuple(data["patch_triggers"]),
        no_release=tuple(data["no_release"]),
    )


# Stale gate-name variants from before the canonical vocabulary was introduced.
# The linter flags any occurrence of these strings outside of gates.json / this
# module. Keep in sync with AI_SHELL_ISSUES.md T1-4.
STALE_GATE_NAMES: tuple[str, ...] = (
    "Pre-commit checks",
    "Security scanning",
    "License compliance",
    "SAST scanning",
    "Quality checks",
    "Validate SAM template",
    "Integration tests",
    "Smoke tests",
    "E2E tests",
)
