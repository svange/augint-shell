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

## CRITICAL: No Rebase on Main

**NEVER use `git pull --rebase` or `git rebase` on `main`.** Use merge commits only.

## CRITICAL: Version Management

**NEVER manually edit version numbers.** Python Semantic Release owns versioning.

- Version in `pyproject.toml` and `src/ai_shell/__init__.py`
- Bumped automatically via conventional commits: `fix:` (patch), `feat:` (minor), `feat!:` (major)
- Tag format: `augint-shell-v{version}`

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

Dev containers mount: project dir, UV cache volume (shared), and conditionally: `~/.claude`, `~/.codex`, `~/.ssh` (ro), `~/.aws`, `~/.gitconfig` (ro), `~/projects/CLAUDE.md` (ro), Docker socket (ro), plus `extra_volumes` from config.

### Environment Assembly

Priority: `extra_env` > `.env` file > `os.environ` > defaults. AWS IAM keys are intentionally NOT passed through (only `AWS_PROFILE` + `AWS_REGION`; relies on `~/.aws` bind mount). `IS_SANDBOX=1` is always set.

### Claude Retry Logic

Default: runs with `-c` (continue previous conversation). If it fails fast (< 5 seconds), retries without `-c` (assumes no prior conversation exists).

### Scaffold System

`ai-shell init` and per-tool `--init`/`--update`/`--clean` flags write tool config files (`.claude/`, `.codex/`, `.agents/`, etc.) into the project. `--clean` removes all managed paths then recreates them fresh.

## CI/CD Pipeline

PR pipeline: pre-commit -> (security scan + compliance + unit tests in parallel). On merge to main: semantic-release -> (PyPI publish + Docker Hub publish + GitHub Pages docs deploy in parallel).

## Testing Patterns

All tests are unit tests in `tests/unit/`. Docker SDK is mocked via fixtures in `conftest.py` (`mock_docker_client`, `mock_container_manager`). CLI tests use Click's `CliRunner` with patched `ContainerManager` and `load_config`. Tests verify command argument building and container creation kwargs, not actual Docker operations.
