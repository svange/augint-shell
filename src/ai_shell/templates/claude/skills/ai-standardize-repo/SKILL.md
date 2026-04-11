---
name: ai-standardize-repo
description: One-command repo standardization umbrella. Runs detection, writes all content files (pipeline, pre-commit, renovate, release, dotfiles), applies GitHub settings and rulesets via ai-gh, then verifies against the canonical contract. Supports --dry-run.
argument-hint: "[--all|--verify|<area>] [--dry-run]"
---

Audit and fix repository standards: $ARGUMENTS

## Sub-commands

- `/ai-standardize-repo` -- show current drift status (read-only, calls verify)
- `/ai-standardize-repo --all` -- run the full 10-step standardization sequence
- `/ai-standardize-repo --all --dry-run` -- compute every would-be change; write nothing; emit a consolidated plan (T5-14)
- `/ai-standardize-repo --verify` -- read-only verify; exits non-zero on any drift
- `/ai-standardize-repo <area>` -- run a single step: `pipeline`, `precommit`, `renovate`, `release`, `dotfiles`, `rulesets`

## Principle: ask before acting

Every sub-skill the umbrella invokes has its own ask-before-acting contract (T5-11 for pipeline, T5-13 for precommit/renovate/release/dotfiles). The umbrella itself does not short-circuit those prompts. If the user aborts any sub-skill's `AskUserQuestion`, the umbrella exits cleanly with a partial report showing which steps completed and which were cancelled. No files stay half-written.

## The 10-step sequence (`--all`)

1. **Detect** repo type x language via `uv run ai-tools standardize <path> --verify --json`. On ambiguity (both `pyproject.toml` and `package.json` present), surface the evidence and ask the user which to choose, then persist their answer to `ai-shell.toml` under `[standardize] language = "..."`.

2. **Dotfiles** -- write `.editorconfig` and `.gitignore` from the bundled templates. The dotfiles sub-skill asks before overwriting existing custom entries (T5-13).

3. **Pre-commit** -- `uv run ai-tools standardize <path> --area precommit`. The precommit sub-skill detects custom hooks and asks whether to preserve, merge, or discard before writing (T5-13).

4. **Pipeline** -- AI-mediated single-file merge. Invoke `/ai-standardize-pipeline` as a sub-skill. The sub-skill (T5-11):
   - Discovers every `.github/workflows/*.yaml` file (not just `pipeline.yaml`) and classifies each by intent: pre-merge pipeline candidate, post-merge deploy helper, post-merge publish helper, scheduled cron, dispatch-only, post-deploy test helper, other
   - Surfaces every ambiguity via `AskUserQuestion` BEFORE writing anything -- filename disambiguation, multi-candidate pre-merge pipelines, custom job preservation, parallel post-deploy test aggregation
   - Merges canonical gates in place, preserves custom jobs verbatim, and writes one `pipeline.yaml` containing all gates inline as a single workflow

   The Python layer (`ai-shell standardize pipeline --validate`) is read-only and provides only the drift report plus canonical job snippets (`--print-template <Gate>`). Do NOT call `ai-shell standardize pipeline --write` -- that flag does not exist. `promote-dev-to-main.nightly.yml` is the only template file that ships separately (iac repos only).

5. **Renovate** -- `uv run ai-tools standardize <path> --area renovate`. The renovate sub-skill detects custom `packageRules` / `matchPackageNames` / `commitMessagePrefix` overrides and asks before rewriting (T5-13).

6. **Release** -- `uv run ai-tools standardize <path> --area release`. The release sub-skill detects custom fields inside `[tool.semantic_release]` (python) or `.releaserc.json` (node) and asks before overwriting (T5-13).

7. **OIDC** -- invoke the `/ai-setup-oidc` skill as a sub-skill. The Python umbrella returns `NEEDS_ACTION` for this step because it does not touch AWS IAM trust policies directly (T5-12). Before invoking the sub-skill, do a quick read-only check of current OIDC trust state:

   - If the repo already has trust policies matching the expected pattern (main branch + dev branch for iac, main only for library): emit `[PASS] oidc: trust already configured for <refs>. Skipping sub-skill.` and continue.
   - If partially configured (e.g. trust exists but the dev branch ref is missing for iac): ask via `AskUserQuestion` -- "Current OIDC trust allows `<refs>`. I'd add `<missing ref>`. OK?"
   - If missing entirely: ask via `AskUserQuestion` -- "This repo has no OIDC trust policy. I'll invoke `/ai-setup-oidc` to create one. OK? Cancel to skip."

   Only after the user confirms does the sub-skill run. Runs before rulesets so deploy jobs have credentials the first time gates enforce.

8. **Repo settings** -- `ai-gh config --standardize` (sets `allow_auto_merge`, `delete_branch_on_merge`, `merge_commit_title=PR_TITLE`; always disables squash merge because it drops semantic-release `[skip ci]` markers on promotion merges).

9. **Rulesets** -- the generator emits one spec file for library repos (single `library` ruleset on the default branch) or two spec files for iac repos (`iac_dev` on `refs/heads/dev` with 5 pre-merge gates, `iac_production` on the default branch with 5 + `Acceptance tests`). For each spec, call `ai-gh rulesets apply <tempfile>`.

10. **Verify** -- `uv run ai-tools standardize <path> --verify`. Reports per-section PASS/DRIFT/FAIL and exits non-zero on any drift.

The stable contract is `ai-tools standardize <path>`; it dispatches to `ai-shell standardize` subcommands under the hood, but skill prose should always call the `ai-tools` wrapper (except for low-level introspection like `ai-shell standardize pipeline --print-template` / `--print-spec`). Sub-skills generate content directly from templates; `ai-gh` is only called for GitHub state mutation (steps 8 and 9).

## Dry-run mode (`--dry-run` / `--plan`)

`/ai-standardize-repo --all --dry-run` runs the full sequence in compute-but-don't-write mode:

- Detection, dotfiles, pre-commit, renovate, release: Python sub-generators are invoked with `dry_run=True` and never write files
- Pipeline: the sub-skill's `AskUserQuestion` loop still runs (so the user still confirms every ambiguity) but the final write step is replaced with a unified diff against the existing `pipeline.yaml`
- OIDC: the read-only pre-check runs; the sub-skill is NOT invoked
- Repo settings: `ai-gh config --standardize --dry-run`
- Rulesets: `ai-gh rulesets apply <spec> --dry-run` for every spec
- Verify: unchanged (already read-only)

The consolidated output looks like:

```
Dry-run plan for /path/to/repo (no files written; no GitHub state mutated)

[OK]            detect: python/library
[OK]            dotfiles: .editorconfig would be updated
[OK]            precommit: would write 1 file(s)
[NEEDS_ACTION]  pipeline: drift detected -- run /ai-standardize-pipeline skill: missing: Compliance, Build validation; legacy: Pre-commit checks->Code quality
[OK]            renovate: would render library-template.json5
[OK]            release: would render python-template.toml
[NEEDS_ACTION]  oidc: [dry-run] OIDC step would delegate to /ai-setup-oidc sub-skill
[OK]            repo_settings: would apply canonical settings via ai-gh config --standardize
[OK]            rulesets: would apply 1 ruleset(s): library
[OK]            verify: 5 section(s) drifted (dry-run: this is the pre-apply baseline, not the post-apply state)

No files have been written. Re-run without --dry-run to apply.
```

Use `--json` with `--dry-run` to emit the plan as structured JSON for CI consumers or tooling pipelines.

## Canonical vocabulary

All gate names come from `gates.json` in this skill directory:

- **Pre-merge gates (all repos):** `Code quality`, `Security`, `Unit tests`, `Compliance`, `Build validation`
- **Post-deploy gate (iac only):** `Acceptance tests`

Commit prefixes and semantic-release alignment come from `commit-scheme.json` in this directory. Never hardcode gate names or commit prefixes in skill prose or template files -- they drift. The `ai-shell standardize lint` command scans for drift and is wired into pre-commit.
