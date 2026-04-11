---
name: ai-standardize-release
description: Generate or validate the semantic-release config for the detected repo type x language (python-semantic-release for Python, semantic-release for Node).
argument-hint: "[--write|--verify]"
---

Generate or validate the semantic-release config: $ARGUMENTS

Primary flow:

1. Detect repo type and language:
   - `uv run ai-shell standardize detect --json`
2. If `--verify` is present, diff the existing config against the template and report drift:
   - `uv run ai-shell standardize release --verify`
3. Otherwise write the canonical config:
   - `uv run ai-shell standardize release --write`

Four code paths, one per `{python,node} x {library,iac}` combination:

- python/library: writes `[tool.semantic_release]` into `pyproject.toml` from `python-template.toml`
- python/iac: same template, branches include both `main` and `dev`
- node/library: writes `.releaserc.json` with plugins including `@semantic-release/npm`
- node/iac: writes `.releaserc.json` without `@semantic-release/npm` (web deploys, not publishes)

After writing, the generator cross-validates the release exclude patterns against `commit-scheme.json` to ensure Renovate prefixes and semantic-release rules stay aligned. Misalignment fails the command with a diagnostic.

Detection of existing config uses TOML parsing (`tomllib.load`) — never a string grep.
