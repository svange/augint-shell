---
name: ai-standardize-repo
description: One-command repo standardization umbrella. Runs detection, writes all content files (pipeline, pre-commit, renovate, release, dotfiles), applies GitHub settings and rulesets via ai-gh, then verifies against the canonical contract.
argument-hint: "[--all|--verify|<area>]"
---

Audit and fix repository standards: $ARGUMENTS

## Sub-commands

- `/ai-standardize-repo` -- show current drift status (read-only, calls verify)
- `/ai-standardize-repo --all` -- run the full 10-step standardization sequence
- `/ai-standardize-repo --verify` -- read-only verify; exits non-zero on any drift
- `/ai-standardize-repo <area>` -- run a single step: `pipeline`, `precommit`, `renovate`, `release`, `dotfiles`, `rulesets`

## The 10-step sequence (`--all`)

1. **Detect** repo type x language via `uv run ai-shell standardize detect --json`. On ambiguity (both `pyproject.toml` and `package.json` present), surface the evidence and ask the user which to choose, then persist their answer to `ai-shell.toml` under `[standardize] language = "..."`.
2. **Dotfiles** -- write `.editorconfig` and `.gitignore` from the bundled templates.
3. **Pre-commit** -- `uv run ai-shell standardize precommit`
4. **Pipeline** -- `uv run ai-shell standardize pipeline`. For iac repos this also writes `.github/workflows/promote-dev-to-main.nightly.yml`.
5. **Renovate** -- `uv run ai-shell standardize renovate`
6. **Release** -- `uv run ai-shell standardize release`
7. **OIDC** -- invoke the `/ai-setup-oidc` skill. Runs before rulesets so deploy jobs have credentials the first time gates enforce.
8. **Repo settings** -- `ai-gh config --standardize` (sets allow_auto_merge, delete_branch_on_merge, merge_commit_title=PR_TITLE; iac repos additionally disable squash merge).
9. **Rulesets** -- the generator emits one spec file for library repos (single `library` ruleset on the default branch) or two spec files for iac repos (`iac_dev` on `refs/heads/dev` with 5 pre-merge gates, `iac_production` on the default branch with 5 + `Acceptance tests`). For each spec, call `ai-gh rulesets apply <tempfile>`.
10. **Verify** -- `uv run ai-shell standardize repo --verify`. Reports per-section PASS/DRIFT/FAIL and exits non-zero on any drift.

All orchestration logic lives in `ai-shell standardize` subcommands; this skill's prose is just the contract for when to invoke which command. Sub-skills generate content directly from templates; `ai-gh` is only called for GitHub state mutation (steps 8 and 9).

## Canonical vocabulary

All gate names come from `gates.json` in this skill directory:

- **Pre-merge gates (all repos):** `Code quality`, `Security`, `Unit tests`, `Compliance`, `Build validation`
- **Post-deploy gate (iac only):** `Acceptance tests`

Commit prefixes and semantic-release alignment come from `commit-scheme.json` in this directory. Never hardcode gate names or commit prefixes in skill prose or template files -- they drift. The `ai-shell standardize lint` command scans for drift and is wired into pre-commit.
