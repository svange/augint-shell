# AGENTS.md

## Project Overview

Python CLI tool (`ai-shell`) for launching AI coding tools and local LLMs in Docker containers. Published to PyPI as `augint-shell`. Replaces Makefile + docker-compose.yml workflow with per-project containers and optional `.ai-shell.toml` config.

## Critical Rules

- **No rebase on main**: NEVER use `git pull --rebase` or `git rebase` on the default branch. Use merge commits only.
- **No manual versioning**: NEVER manually edit version numbers. Semantic Release manages versions via conventional commits.
- **No lock file edits**: NEVER directly write text into lock files (uv.lock, package-lock.json, poetry.lock, yarn.lock). Always use package manager commands (`uv lock`, `uv add`, `npm install`) to regenerate them. When a package manager command updates a lock file, ALWAYS stage and include it in the commit.
- **No .env commits**: NEVER commit .env files. Use .env.example for templates.
- **No force push to main**: NEVER use `git push --force` on main or the default branch.

## Development Commands

```bash
uv sync --all-extras                         # Install dependencies
uv run pytest                                # Run tests
uv run pytest --cov=src --cov-fail-under=80  # Tests with coverage
uv run ruff check src/                       # Lint
uv run ruff format src/ tests/               # Format
uv run mypy src/                             # Type check
uv run pre-commit run --all-files            # Run all pre-commit hooks
```

## Conventions

- **Commits**: Conventional commits required. `fix:` = patch, `feat:` = minor, `feat!:` / `BREAKING CHANGE` = major.
- **Branches**: `{type}/issue-N-description` where type is one of: feat, fix, docs, refactor, test, chore, ci, build, style, revert, perf.
- **PRs**: Target the default development branch. Enable automerge.
- **Pre-commit**: Run `uv run pre-commit run --all-files` explicitly before committing (no automatic git hooks -- they break across Windows/WSL). If checks fail, fix the issue and create a NEW commit (do not amend).
- **Tests**: Write tests for all new functionality. Bug fixes require regression tests.

## Development Workflow

1. **Pick an issue**: `/ai-pick-issue` -- find or get assigned work
2. **Prepare branch**: `/ai-prepare-branch` -- REQUIRED before any code changes
3. **Develop**: Write code with tests, following project conventions
4. **Submit**: `/ai-submit-work` -- full checks, commit, push, automerge PR
5. **Monitor**: `/ai-monitor-pipeline` -- watches CI, diagnoses failures, auto-fixes and re-pushes

## ai-tools

- Single-repo commands: `ai-tools repo <command>`
- Workspace/monorepo commands: `ai-tools mono <command>`
- Standardization commands: `ai-tools standardize <command>`
- `augint-tools` is the project/repository name; `ai-tools` is the CLI command to run.
- Prefer machine-readable output (`--json`) when available for agent consumption.

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

1. **Per-project dev containers** (`augint-shell-{project}-dev`): One per project directory. Uses `tail -f /dev/null` to stay alive, commands exec into it.
2. **Host-level LLM stack** (singletons): Ollama + Open WebUI shared across all projects via `augint-shell-llm` Docker network.

### Config Layering (highest priority first)

1. CLI flags (`--project`)
2. Environment variables (`AI_SHELL_*` prefix)
3. Project `.ai-shell.toml`
4. Global `~/.config/ai-shell/config.toml`
5. Hard-coded defaults in `defaults.py`
