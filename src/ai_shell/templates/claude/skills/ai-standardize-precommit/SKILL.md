---
name: ai-standardize-precommit
description: Generate or validate the canonical pre-commit hook setup (.pre-commit-config.yaml for Python; husky + lint-staged for Node).
argument-hint: "[--write|--verify]"
---

Generate or validate pre-commit setup: $ARGUMENTS

Primary flow:

1. Detect language:
   - `uv run ai-shell standardize detect --json`
2. If `--verify` is present, diff the local config against the template and report drift:
   - `uv run ai-shell standardize precommit --verify`
3. Otherwise write the canonical config:
   - `uv run ai-shell standardize precommit --write`

Python path: writes `.pre-commit-config.yaml` from `python-template.pre-commit-config.yaml` (ruff format, ruff check, mypy, uv-lock-check, forbid-env, trailing-whitespace, end-of-file-fixer, check-yaml).

Node path: writes `.husky/pre-commit` (runs `npx lint-staged`) and `lint-staged.config.json` from the bundled node templates. Merges `"prepare": "husky install"` into `package.json.scripts`. Idempotent on a second run.

The same checks run in the `Code quality` CI gate so local hooks and CI enforce the same rules.
