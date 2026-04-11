---
name: ai-standardize-renovate
description: Generate or validate the canonical Renovate config (renovate.json5) with ecosystem substitution for detected repo type x language.
argument-hint: "[--write|--verify]"
---

Generate or validate `renovate.json5`: $ARGUMENTS

Primary flow:

1. Detect repo type and language:
   - `uv run ai-shell standardize detect --json`
2. If `--verify` is present, diff the existing `renovate.json5` against what the generator would produce and report drift:
   - `uv run ai-shell standardize renovate --verify`
3. Otherwise write the canonical config:
   - `uv run ai-shell standardize renovate --write`

The generator picks `library-template.json5` or `iac-template.json5` from the `ai-standardize-repo` skill directory and substitutes manager names and dep type strings for the detected language:

- Python: `pep621` manager, `project.dependencies`, `project.optional-dependencies`, `dependency-groups`
- Node: `npm` manager, `dependencies`, `devDependencies`

For node/iac the generator forces `automergeStrategy: merge` (never `squash`, which drops `[skip ci]` and breaks the promotion cycle).

Commit prefixes are cross-validated against `commit-scheme.json` (the canonical Renovate <-> semantic-release alignment).
