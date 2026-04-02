# CLAUDE.md - augint-shell

Python CLI tool for launching AI coding tools and local LLMs in Docker containers. Published to PyPI as `augint-shell`, CLI command is `ai-shell`.

## What This Tool Does

Replaces Makefile + docker-compose.yml workflow:
- Launch AI tools (Claude Code, Codex, opencode, aider) in Docker containers
- Manage local LLM stack (Ollama + Open WebUI) with GPU auto-detection
- Per-project containers with unique names for concurrent usage
- Optional `ai-shell.toml` config for per-project customization

## CLI Commands

```bash
# AI tools (each launches in a per-project Docker container)
ai-shell claude            # Launch Claude Code
ai-shell claude-x          # Claude with --dangerously-skip-permissions
ai-shell codex             # Launch Codex
ai-shell opencode          # Launch opencode
ai-shell aider             # Launch aider with local LLM
ai-shell shell             # Bash shell in container

# LLM stack (host-level singletons)
ai-shell llm up            # Start Ollama + Open WebUI
ai-shell llm down          # Stop LLM stack
ai-shell llm pull          # Pull models
ai-shell llm setup         # First-time setup (up + pull + configure)
ai-shell llm status        # Show status and models
ai-shell llm logs          # Tail logs
ai-shell llm shell         # Shell in Ollama container

# Container management
ai-shell manage status     # Show dev container status
ai-shell manage stop       # Stop dev container
ai-shell manage clean      # Remove container + volumes
ai-shell manage logs       # Tail dev container logs
ai-shell manage pull       # Pull latest Docker image
```

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check src/
uv run mypy src/
```

## CRITICAL: No Rebase on Main

**NEVER use `git pull --rebase` or `git rebase` on `main`.** Use merge commits only.

## CRITICAL: Version Management

**NEVER manually edit version numbers.** Python Semantic Release owns versioning.

- Version in `pyproject.toml` and `src/ai_shell/__init__.py`
- Bumped automatically via conventional commits:
  - `fix:` -> patch
  - `feat:` -> minor
  - `feat!:` -> major
- Tag format: `augint-shell-v{version}`

## Testing

```bash
uv run pytest                              # All tests
uv run pytest --cov=src --cov-fail-under=80  # With coverage
```

## File Structure

```
src/ai_shell/
├── __init__.py       # Version, public exports
├── defaults.py       # Constants, mount/env builders
├── config.py         # TOML config loading
├── container.py      # Docker SDK container lifecycle
├── gpu.py            # NVIDIA GPU detection
├── exceptions.py     # Error hierarchy
└── cli/
    ├── __main__.py   # Click entry point
    └── commands/
        ├── tools.py  # claude, codex, opencode, aider, shell
        ├── llm.py    # llm up/down/pull/setup/status/logs/shell
        └── manage.py # manage stop/clean/status/logs/pull
```
