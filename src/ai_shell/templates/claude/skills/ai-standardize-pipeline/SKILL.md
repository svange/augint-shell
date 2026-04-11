---
name: ai-standardize-pipeline
description: Generate or validate the canonical CI/CD pipeline workflow (.github/workflows/pipeline.yaml) from gates.json and detected repo type x language.
argument-hint: "[--write|--verify]"
---

Generate or validate the canonical `pipeline.yaml`: $ARGUMENTS

Primary flow:

1. Detect repo type and language:
   - `uv run ai-shell standardize detect --json`
2. If `--verify` is present, compare `.github/workflows/pipeline.yaml` against the template the generator would produce and report drift:
   - `uv run ai-shell standardize pipeline --verify`
3. Otherwise write the canonical pipeline:
   - `uv run ai-shell standardize pipeline --write`

The generator reads `gates.json` from the `ai-standardize-repo` skill directory (the canonical vocabulary) and selects the template that matches `{python,node} x {library,iac}`. It writes `.github/workflows/pipeline.yaml` directly. For iac repos it additionally writes `.github/workflows/promote-dev-to-main.nightly.yml`.

After writing, the generator re-reads the file and asserts that every `jobs.<id>.name` matches a canonical gate name from `gates.json`. If the template drifts from the vocabulary the command aborts.

Report:

- detected repo type x language
- template selected
- jobs written and their canonical gate names
- any drift findings when `--verify` is used
