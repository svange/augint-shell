"""Repo standardization generators and verifiers.

Each submodule owns one section of the one-command `/ai-standardize-repo --all`
orchestration: gates vocabulary, detection, pipeline, precommit, renovate,
release, rulesets, verify, umbrella. Skill prose invokes these via the
`ai-shell standardize ...` subcommand tree.
"""

from __future__ import annotations
