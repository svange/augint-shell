---
name: ai-standardize-precommit
description: Detect-and-ask before writing the canonical pre-commit hook setup (.pre-commit-config.yaml for Python; husky + lint-staged for Node). Surfaces custom hooks via AskUserQuestion before any overwrite.
argument-hint: "[<repo path>]"
---

Standardize pre-commit hooks at $ARGUMENTS (defaults to cwd).

The same `Code quality` CI gate enforces these checks on PRs; local
hooks give developers the same feedback before they push.

## Core principle: ask before acting

Never silently overwrite custom hooks or stage filters the user has
authored. Detect drift, classify it, and ask via `AskUserQuestion`
before writing. If the user aborts, exit with
`Standardization aborted by user. No files were modified.`

## Process

### Step 1 -- detect language

```bash
uv run ai-shell standardize detect --json <repo>
```

Note the language (python/node). On ambiguous, ask the user and stop.

### Step 2 -- read the existing config (if present)

- **Python path**: `Read <repo>/.pre-commit-config.yaml`
- **Node path**: `Read <repo>/.husky/pre-commit` and
  `Read <repo>/lint-staged.config.json`

If absent entirely, skip to Step 4 with one confirmation question:
> No existing pre-commit config. Scaffold the canonical template? [a]
> Yes. [b] Abort.

### Step 3 -- diff against canonical and classify

Parse the existing config and categorize every entry into three groups:

1. **Canonical content that already matches** -- no action needed.
2. **Canonical content that drifted** -- e.g. a ruff-check hook is
   present but with different `args:` or `files:` filters. Plan to
   rewrite.
3. **Custom content** -- hooks, repos, stage filters, `exclude:`
   patterns the user authored that are NOT in the canonical template.

**Python custom content to detect:**

- Custom hooks in `repos:` that aren't in the canonical template's hook
  set (ruff-format, ruff-check, mypy, uv-lock-check, forbid-env,
  trailing-whitespace, end-of-file-fixer, check-yaml, gitleaks,
  check-added-large-files)
- Custom `stages:` filters beyond the canonical `commit` stage
- Custom `exclude:` patterns at repo, hook, or file level beyond the
  SAM-exclude substitution (which is handled by the generator
  automatically when `template.yaml` is present in the repo root)
- Custom `language:` or `entry:` overrides on canonical hooks

**Node custom content to detect:**

- Custom globs in `lint-staged.config.json` beyond the canonical
  `*.{ts,tsx,vue,js,jsx}` and `*.{json,md,yml,yaml}` patterns
- Custom entries in `package.json.scripts` related to pre-commit beyond
  `"prepare": "husky install"`
- Custom husky hooks beyond `pre-commit`

### Step 4 -- ask before acting

For each item in the "custom content" category, describe it and ask via
`AskUserQuestion`. Group related items into one question where possible:

> Your existing `.pre-commit-config.yaml` has 3 custom hooks that are
> not in the canonical template: `check-added-large-files` (from
> pre-commit-hooks), `bandit` (from PyCQA/bandit), `codespell` (from
> codespell-project/codespell). Options:
> [a] Preserve all 3 alongside the canonical hooks (recommended).
> [b] Preserve some (I'll ask per hook).
> [c] Discard all 3 and use canonical only.
> [d] Abort.

For each item in the "canonical content that drifted" category,
describe the drift and ask:

> Your existing `ruff-check` hook runs `uv run ruff check --fix src/`
> (missing `tests/`). The canonical version runs `uv run --no-sync
> ruff check --fix src/ tests/`. [a] Rewrite to canonical (recommended
> -- same rules as CI). [b] Preserve the drifted version. [c] Abort.

### Step 5 -- write the merged file

Only after every question is answered, call the Python generator:

```bash
uv run ai-shell standardize precommit <repo>
```

This writes `.pre-commit-config.yaml` (python) or `.husky/pre-commit` +
`lint-staged.config.json` + `package.json` scripts merge (node). The
Python generator handles the deterministic pieces (template loading,
SAM-exclude substitution when `template.yaml` is detected, idempotent
`prepare` script merging).

For custom hooks the user chose to preserve, you (the AI) must insert
them back into the generated file via `Read` + `Edit` after the Python
generator runs. The generator writes canonical-only content; preserving
custom content is your responsibility in the skill layer.

### Step 6 -- verify

Re-run `Read` on the written file and confirm:

- All canonical hooks are present with their canonical configuration
- All preserved-custom hooks are present with their original
  configuration
- No unanswered custom content was silently lost

Report the count of canonical hooks written, custom hooks preserved,
and any hooks the user chose to discard.

## Constraints

- **Zero writes before every question is answered.** The ask-before-
  acting principle is the core contract of this skill.
- **SAM exclude is automatic.** If the repo has `template.yaml` or
  `template.yml` at the root, the python generator already renders the
  `check-yaml: exclude:` line for SAM templates via substitution -- do
  NOT ask about that unless the user's existing config has a different
  exclude pattern.
- **Same rules as CI.** The canonical python hooks match the `Code
  quality` CI gate exactly (ruff format, ruff check, mypy,
  uv-lock-check, gitleaks, etc.). Drift here means drift between local
  and CI behavior, which is always worth flagging.
