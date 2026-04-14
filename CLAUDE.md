# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Python CLI tool (`ai-shell`) for launching AI coding tools and local LLMs in Docker containers. Published to PyPI as `augint-shell`. Replaces Makefile + docker-compose.yml workflow with per-project containers and optional `ai-shell.toml` config.

## Development

```bash
uv sync --all-extras                       # Install all deps
uv run pytest                              # All tests
uv run pytest tests/unit/test_config.py    # Single test file
uv run pytest -k "test_load_missing"       # Single test by name
uv run pytest --cov=src --cov-fail-under=80  # With coverage
uv run ruff check src/                     # Lint
uv run ruff format src/ tests/             # Format
uv run mypy src/                           # Type check
uv run pre-commit run --all-files          # All pre-commit hooks
```

## Pre-commit Hooks

Hooks run automatically: YAML check, trailing whitespace, end-of-file newline, `.env` file blocker, ruff format + lint (with auto-fix), mypy, and uv.lock freshness check.

## Critical Rules

- **No rebase on main**: NEVER use `git pull --rebase` or `git rebase` on the default branch. Use merge commits only.
- **No manual versioning**: NEVER manually edit version numbers. Python Semantic Release owns versioning via conventional commits. Version in `pyproject.toml` and `src/ai_shell/__init__.py`. Tag format: `v{version}`.
- **No lock file edits**: NEVER directly write text into lock files (uv.lock, package-lock.json, poetry.lock, yarn.lock). Always use package manager commands (`uv lock`, `uv add`, `npm install`) to regenerate them. When a package manager command updates a lock file, ALWAYS stage and include it in the commit -- lock file changes must never be left uncommitted.
- **No .env commits**: NEVER commit .env files. Use .env.example for templates.
- **No force push to main**: NEVER use `git push --force` on main or the default branch.
- **No CI control keywords**: NEVER include GitHub Actions CI control keywords in commit messages, PR titles, PR descriptions, or any text that becomes part of a merge commit. The forbidden strings are: `[skip ci]`, `[ci skip]`, `[no ci]`, `[skip actions]`, `[actions skip]`. GitHub scans the full commit message (title + body, including merge commit bodies derived from PR descriptions) and will skip all workflows if any of these strings appear anywhere -- even inside backticks, quotes, or explanatory text. Only `semantic-release` is authorized to emit these keywords in its automated release commits.

## Conventions

- **Commits**: Conventional commits required. `fix:` = patch, `feat:` = minor, `feat!:` / `BREAKING CHANGE` = major.
- **Branches**: `{type}/issue-N-description` where type is one of: feat, fix, docs, refactor, test, chore, ci, build, style, revert, perf.
- **PRs**: Target the default development branch. Enable automerge. For service/service repos, use merge commits (do not squash).
- **Pre-commit**: Run `uv run pre-commit run --all-files` explicitly before committing (no automatic git hooks -- they break across Windows/WSL). If checks fail, fix the issue and create a NEW commit (do not amend).
- **Tests**: Write tests for all new functionality. Bug fixes require regression tests.

## Development Workflow

**IMPORTANT**: Always follow this sequence. Do NOT skip to step 3 without completing step 2 first.

1. **Pick an issue**: `/ai-pick-issue` -- find or get assigned work
2. **Prepare branch**: `/ai-prepare-branch` -- REQUIRED before any code changes. Creates a fresh branch from the latest base (main or dev), syncs upstream, sets up remote tracking. Never start coding on an existing branch from a previous task.
3. **Develop**: Write code with tests, following project conventions
4. **Present next steps**: After completing development, show the user what changed (brief summary) and present a context-aware menu:

   **On a feature branch** (`feat/*`, `fix/*`, etc.):
   1. **Commit only** -- stage, run pre-commit, commit with conventional message
   2. **Commit + push** -- same as 1, then push to remote
   3. **Submit PR** -- `/ai-submit-work`: full checks, commit, push, automerge PR, then monitor pipeline
   4. **Show diff first** -- review changes before deciding

   **On dev/staging/main** (shouldn't normally be here):
   1. **Move to feature branch** -- create branch, move uncommitted changes there
   2. **Commit directly** -- with explicit warning:
      - `main`: triggers semantic-release, PyPI publish, Docker publish, docs deploy
      - `dev`/`staging`: may trigger staging deployment

   Always present the menu. Never auto-commit or auto-submit without the user choosing.

5. **Monitor** (after PR): `/ai-monitor-pipeline` -- watches CI, diagnoses failures, auto-fixes and re-pushes

## ai-tools

`augint-tools` is the project/repository name; `ai-tools` is the CLI command.

- Single-repo commands: `uv run ai-tools repo <command>`
- Workspace commands: `uv run ai-tools workspace <command>`
- Standardization commands: `uv run ai-tools standardize [PATH] [--verify|--all|--area <x>]`
- Run `ai-tools standardize <child-path>` **from the workspace root**; never `cd` into a child. `uv run` inside a child re-solves the child lockfile and can downgrade augint-tools in the shared workspace venv.
- `ai-tools standardize` is the stable user-facing contract; `ai-shell standardize` is the implementation layer (skill prose should call `ai-tools`, not `ai-shell`, except for low-level introspection like `--print-template` / `--print-spec`).
- Use repo-local skills as thin wrappers for `ai-tools` commands.
- Prefer machine-readable output (`--json`) and summarize actionable results.
- Branch, PR target, and validation policy should come from repo or workspace config, not guesswork.

## Key Commands

```bash
# Git
git status                    # Check working tree
git log --oneline -10         # Recent commits

# GitHub CLI
gh issue list --state open    # View open issues
gh pr create                  # Create pull request
gh pr merge --auto --merge    # Enable automerge
gh run list                   # List workflow runs
gh run view <id>              # View run details
gh run watch <id>             # Watch run in real-time
```

## Architecture

### Dependency Flow

```
CLI commands (cli/commands/)
  -> ContainerManager (container.py)
    -> AiShellConfig (config.py)
    -> defaults.py (constants, mount/env builders)
    -> gpu.py (NVIDIA detection)
```

### Two Container Categories

1. **Per-project dev containers** (`augint-shell-{project}-dev`): One per project directory, runs all AI tools. Created on-demand, reused if running. Uses `tail -f /dev/null` to stay alive, commands exec into it.

2. **Host-level LLM stack** (singletons): Ollama + Open WebUI containers shared across all projects via `augint-shell-llm` Docker network. Persistent named volumes. GPU auto-detected for Ollama.

### Config Layering (highest priority first)

1. CLI flags (`--project`)
2. Environment variables (`AI_SHELL_*` prefix)
3. Project `ai-shell.toml`
4. Global `~/.config/ai-shell/config.toml`
5. Hard-coded defaults in `defaults.py`

### Container Naming

`project_dir.name` -> `sanitize_project_name()` (lowercase, special chars to hyphens, collapsed) -> `dev_container_name()` -> `augint-shell-{name}-dev`. Override with `--project` flag.

### Mount Assembly

Dev containers mount: project dir, UV cache volume (shared), and conditionally: `~/.claude`, `~/.codex`, `~/.ssh` (ro), `~/.aws`, `~/.config/gh`, `~/.gitconfig` (ro), `~/projects/CLAUDE.md` (ro), Docker socket (ro), plus `extra_volumes` from config.

### Environment Assembly

Priority: `extra_env` > `.env` file > `os.environ` > defaults. AWS IAM keys are intentionally NOT passed through (only `AWS_PROFILE` + `AWS_REGION`; relies on `~/.aws` bind mount). `IS_SANDBOX=1` is always set.

### Claude Retry Logic

Default: runs with `-c` (continue previous conversation). If it fails fast (< 5 seconds), retries without `-c` (assumes no prior conversation exists).

### Scaffold System

`ai-shell init` and per-tool `--init`/`--update`/`--reset`/`--clean` flags write tool config files (`.claude/`, `.codex/`, `.agents/`, etc.) into the project. `--update` merges settings (preserves user customizations) and overwrites managed skills. `--reset` force-overwrites all managed files. `--clean` removes all managed paths then recreates them fresh.

**Claude Code skills** are delivered via the `augint-workflow` plugin in the `ai-cc-tools` repo, not scaffolded by `ai-shell`. `ai-shell claude --init` only writes `settings.json`. Skills for agents/opencode/codex are still scaffolded from `src/ai_shell/templates/agents/skills/`.

### Branch Detection Algorithm (Shared Across Skills)

All workflow skills (ai-prepare-branch, ai-submit-work, ai-monitor-pipeline, ai-promote, ai-status, ai-rollback) use this same logic. Update here and propagate to skills when changed.

1. Check `ai-shell.toml` for `[workflow] dev_branch` override (wins if set)
2. Check remote branches (priority order): `origin/dev` > `origin/develop` > `origin/staging`
3. First match = dev branch. Repo is a "service" (deploy pattern: service/web/backend/frontend).
4. No match = "library" repo (publish pattern, main-only).
5. Default branch = `git symbolic-ref refs/remotes/origin/HEAD` or fallback `main`
6. Base branch for new work = dev branch if found, else default branch

```bash
DEV_BRANCH=""
for candidate in dev develop staging; do
    if git show-ref --verify --quiet refs/remotes/origin/$candidate; then
        DEV_BRANCH=$candidate
        break
    fi
done
DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' || echo "main")
BASE=${DEV_BRANCH:-$DEFAULT_BRANCH}
```

## CI/CD Pipeline

### 5 Universal Pre-Merge Gates (all repos)

Canonical vocabulary from `gates.json` in `ai-standardize-repo` skill:

1. **Code quality** - linting, formatting, type checking, file hygiene
2. **Security** - Bandit/Semgrep SAST + dependency vulnerability scanning
3. **Unit tests** - tests + coverage threshold (>=80%)
4. **Compliance** - GPL/AGPL license blocking
5. **Build validation** - `uv build` / `sam build` / `cdk synth` / `vite build` / `terraform validate`

### 1 Post-Deploy Gate (service/service repos only)

6. **Acceptance tests** - runs against staging after dev deploy; required on main ruleset only

### 2 Project Types

- **library** (main-only): release -> publish (PyPI/npm) -> docs
- **service** (dev+main): deploy staging -> integration tests -> deploy prod -> release

### Pipeline Architecture

Single `pipeline.yaml` per repo. All canonical gates inline as jobs in one workflow. No reusable-workflow split. AI-mediated merge via `/ai-standardize-pipeline` — the Python layer is read-only (`validate(path)`, `canonical_jobs(lang, type)`); the skill prose drives Claude through reading, legacy-rename, missing-gate insertion, and custom-job preservation.

See `README.md` "Standardization architecture" for the full ownership matrix, detection rules, pipeline principles, and execution scopes. The sections below are the action-oriented hot list.

## Standardization do-not rules

Lessons learned across five rounds of iteration. Violating any of these will break something that was carefully designed to work:

- **Do not** split `pipeline.yaml` into reusable workflows (`_gate-*.yaml` with `uses:` calls). This fragments the GitHub Actions UI into one row per gate, destroys the unified DAG view, and was explicitly reverted in T5-7. One inline file, all jobs visible in one workflow run.
- **Do not** write a Python merge engine that reshapes `pipeline.yaml` programmatically. The merge is AI-mediated; Python provides only `validate()` and `canonical_jobs()` as the deterministic substrate. Static merge engines cannot handle parallel post-deploy patterns, custom report aggregators, or ephemeral test-infra jobs.
- **Do not** introduce a two-phase migration ("run once to scaffold, hand-edit, run again"). Standardization is one invocation per repo.
- **Do not** use `.ai-shell.toml` for repo-shape or workspace-shape detection. That file is scoped to AI agent configuration (container settings, model provider). Repo shape is detected by `ai-shell standardize detect`; workspace shape is read via `ai-tools workspace inspect` from `workspace.yaml`.
- **Do not** allow squash merge on any repo type. Squash drops the `[skip ci]` marker semantic-release emits on promotion merges and breaks the dev->main release cycle. All repos use merge commits. `ai-gh config --standardize` enforces this.
- **Do not** delete org-inherited rulesets during verify or apply. `verify._verify_rulesets` filters them out by `source_type == "Organization"`; only repo-scope branch rulesets participate in drift computation.
- **Do not** call `ai-shell standardize ...` directly from skill prose (except the low-level `pipeline --print-template` / `pipeline --print-spec` introspection commands). The stable contract is `ai-tools standardize <path> [--verify|--all|--area <area>]`; the `ai-shell` commands are the implementation layer underneath. Calling `ai-shell` directly bypasses the wrapper's path/argument handling.
- **Do not** introduce hard `==` version pins in any generated config or template. Floor-only `>=X.Y.Z` pins are fine; Renovate-managed SHA pins (`@<sha> # vX.Y.Z`) in workflow `uses:` lines are fine. Hard exact pins break dependency resolution across the monorepo shared venv.
- **Do not** `cd` into a child repo when orchestrating workspace-level commands. Always pass the child path as an argument. Reason: the workspace shares a single venv and `uv run` re-solves against the child's `pyproject.toml` floor, downgrading the venv for every subsequent child. Fix: always invoke from the workspace root with `<child-path>` args. Documented in `/ai-workspace-standardize`.
- **Do not** hand-edit files under `.agents/skills/`. Those are scaffolded from `src/ai_shell/templates/agents/skills/`. Edit the templates and re-run scaffold (or run `/ai-init --reset` in the consumer repo). Claude Code skills live in the `augint-workflow` plugin in the `ai-cc-tools` repo.

## Testing Patterns

All tests are unit tests in `tests/unit/`. Docker SDK is mocked via fixtures in `conftest.py` (`mock_docker_client`, `mock_container_manager`). CLI tests use Click's `CliRunner` with patched `ContainerManager` and `load_config`. Tests verify command argument building and container creation kwargs, not actual Docker operations.
