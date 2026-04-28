# CLAUDE.md

Project-specific guidance for Claude Code. All canonical workflow, CI, commit, and standardization rules live in the `ai-cc-tools` plugin (`augint-workflow`, `ai-standardize-*` skills) — do not duplicate them here.

## Overview

Python CLI tool (`ai-shell`) for launching AI coding tools and local LLMs in Docker containers. Published to PyPI as `augint-shell`. Replaces Makefile + docker-compose.yml workflow with per-project containers and optional `.ai-shell.yaml` config.

## Development

```bash
uv sync --all-extras                         # Install all deps
uv run pytest                                # All tests
uv run pytest tests/unit/test_config.py      # Single test file
uv run pytest -k "test_load_missing"         # Single test by name
uv run pytest --cov=src --cov-fail-under=80  # With coverage
uv run ruff check src/                       # Lint
uv run ruff format src/ tests/               # Format
uv run mypy src/                             # Type check
uv run pre-commit run --all-files            # All pre-commit hooks
```

## Architecture

### Dependency flow

```
CLI commands (cli/commands/)
  -> ContainerManager (container.py)
    -> AiShellConfig (config.py)
    -> defaults.py (constants, mount/env builders)
    -> gpu.py (NVIDIA detection)
```

### Two container categories

1. **Per-project dev containers** (`augint-shell-{project}-dev`) — one per project directory. Created on-demand, reused if running. Uses `tail -f /dev/null` to stay alive; commands exec into it.
2. **Host-level LLM stack** (singletons) — Ollama, Open WebUI, Kokoro TTS, Speaches STT, voice-agent, and n8n containers shared across projects via the `augint-shell-llm` Docker network. Persistent named volumes. GPU auto-detected for Ollama, Kokoro, and Whisper; those containers auto-recreate when GPU availability changes. Voice-agent image is built locally on first use.

### Config layering (highest priority first)

1. CLI flags (`--project`)
2. Environment variables (`AI_SHELL_*` prefix)
3. Project config (first match: `.ai-shell.yaml` > `.ai-shell.yml` > `.ai-shell.toml` > `ai-shell.toml`)
4. Global config (`~/.ai-shell.yaml` > `~/.ai-shell.yml` > `~/.ai-shell.toml` > `~/.config/ai-shell/config.*`)
5. Hard-coded defaults in `defaults.py`

### Container naming

`project_dir.name` -> `sanitize_project_name()` (lowercase, special chars to hyphens, collapsed) -> `dev_container_name()` -> `augint-shell-{name}-dev`. Override with `--project` flag.

### Mount assembly

Dev containers mount: project dir, UV cache volume (shared), and conditionally: `~/.claude`, `~/.codex`, `~/.pi`, `~/.ssh` (ro), `~/.aws`, `~/.config/gh`, `~/.gitconfig` (ro), `~/projects/CLAUDE.md` (ro), Docker socket (ro), plus `extra_volumes` from config.

### Environment assembly

Priority: `extra_env` > `.env` file > `os.environ` > defaults. AWS IAM keys are intentionally NOT passed through (only `AWS_PROFILE` + `AWS_REGION`; relies on `~/.aws` bind mount). `IS_SANDBOX=1` is always set. `OPENCODE_SERVER_PASSWORD` and `OPENCODE_SERVER_USERNAME` are passed through when set. `PATH` includes `/root/.opencode/bin`.

### OpenCode web mode

`opencode` is a Click group (`invoke_without_command=True`). Default invocation launches the TUI; subcommands add web server features.

- **`opencode --web`** — runs `opencode web` inside the container with `--mdns`, `--cors '*'`, `--hostname 0.0.0.0`. Interactive (foreground).
- **`opencode serve`** — runs `opencode serve` detached (`exec_detached()`), then discovers git repos under CWD and runs `opencode attach <url>` for each as background processes. Prints server URL, mDNS name, and attached repo list.
- **`opencode status`** — parses `pgrep -af opencode` output inside the container to show server state and attached terminal count.

mDNS domain defaults to `sanitize_project_name().local`. `OPENCODE_SERVER_PASSWORD` and `OPENCODE_SERVER_USERNAME` are resolved from `.env` / `os.environ` in `build_dev_environment()`. PATH includes `/root/.opencode/bin` so `opencode` is available in interactive shells.

### Claude retry logic

Default: runs with `-c` (continue previous conversation). If it fails fast (< 5 seconds), retries without `-c` (assumes no prior conversation exists).

### Pi integration

Pi (`@mariozechner/pi-coding-agent`) is a provider-agnostic terminal coding agent installed via npm. It connects to Ollama via `models.json` (template in `src/ai_shell/templates/pi/`). The `ai-shell pi` command checks Ollama is running before launch. Config persists via `~/.pi` bind mount. Supports `--aws` (Bedrock), `--openai-profile`, and `--login` (OAuth).

### Scaffold system

`ai-shell init` and per-tool `--init`/`--update`/`--reset`/`--clean` flags write tool config files (`.claude/`, `.codex/`, `.agents/`, etc.) into the project. `--update` merges settings (preserves user customizations) and overwrites managed skills. `--reset` force-overwrites all managed files. `--clean` removes all managed paths then recreates them fresh.

**Claude Code skills** are delivered via the `augint-workflow` plugin in the `ai-cc-tools` repo, not scaffolded by `ai-shell`. `ai-shell claude --init` only writes `settings.json`. Skills for agents/opencode/codex are still scaffolded from `src/ai_shell/templates/agents/skills/`.

## Testing

All tests are unit tests in `tests/unit/`. Docker SDK is mocked via fixtures in `conftest.py` (`mock_docker_client`, `mock_container_manager`). CLI tests use Click's `CliRunner` with patched `ContainerManager` and `load_config`. Tests verify command argument building and container creation kwargs, not actual Docker operations.

## Project-specific notes

- Version lives in `pyproject.toml:project.version` and `src/ai_shell/__init__.py:__version__`. Python Semantic Release owns both.
- Tag format is `v{version}` (canonical per ai-standardize-release).
- Do not hand-edit files under `.agents/skills/` — scaffolded from `src/ai_shell/templates/agents/skills/`. Edit the templates and re-run scaffold.
