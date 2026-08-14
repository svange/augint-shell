# Repository Guidelines

## Project Structure & Module Organization
`src/ai_shell/` contains the packaged CLI and runtime modules. Core behavior lives in files such as `config.py`, `container.py`, `local_chrome.py`, and `tmux.py`; CLI entrypoints are under `src/ai_shell/cli/`. Project templates ship in `src/ai_shell/templates/`. Tests live in `tests/unit/` and follow the source module layout with `test_*.py` files. CI support assets are in `ci-resources/`, Docker packaging is in `docker/`, and automation/workflow definitions are in `.github/workflows/` and `.agents/`.

## Build, Test, and Development Commands
Use `uv` for local development.

- `uv sync --frozen --all-extras` installs the locked dev environment.
- `uv run pytest --cov=src --cov-fail-under=80 -v` runs the unit suite with the same 80% coverage floor enforced in CI.
- `uv run pre-commit run --all-files` runs formatting, linting, typing, YAML, and lockfile checks.
- `uv run ruff format src/ tests/` formats Python code.
- `uv run ruff check --fix src/ tests/` applies lint fixes.
- `uv run mypy src/` runs static typing.
- `uv build` builds the package; release automation also refreshes `uv.lock`.

## Coding Style & Naming Conventions
Target Python 3.12+ and keep lines within Ruff’s `100` character limit. Use 4-space indentation, snake_case for modules/functions, PascalCase for classes, and explicit type hints for production code; `mypy` is configured with `disallow_untyped_defs = true` for most modules. Keep CLI-specific exceptions narrowly scoped inside `src/ai_shell/cli/`. Let Ruff handle import ordering and formatting instead of manual styling.

## Testing Guidelines
Add unit tests in `tests/unit/` using `test_<module>.py` naming. Prefer focused tests around CLI behavior, configuration parsing, Docker/container flows, and local Chrome integration. Run `uv run pytest -ra -q` before opening a PR; include coverage-sensitive tests when touching logic in `src/`.

## Commit & Pull Request Guidelines
Git history uses Conventional Commits, for example `feat: ...`, `fix: ...`, and `chore(release): ...`. Keep subjects imperative and scoped to one change. Pull requests should summarize behavior changes, link the relevant issue when applicable, and note any config, Docker, or release impacts. Include terminal output or screenshots only when they clarify CLI-visible changes.

## Security & Configuration Tips
Do not commit `.env` files; pre-commit blocks them. Keep project-specific settings in `ai-shell.toml` or `~/.config/ai-shell/config.toml`, and update `uv.lock` whenever dependencies change.

### Release credential (`GH_TOKEN`)
`main` is a protected branch, and `semantic-release` pushes the release commit and the `v{version}` tag directly to it. The default `GITHUB_TOKEN` cannot do that, so the `Semantic release` job in `.github/workflows/publish.yaml` authenticates with the `GH_TOKEN` repository secret — a personal access token whose account can bypass the protection on `main`. `pyproject.toml` wires the same secret into `[tool.semantic_release.remote.token]`, and the `Deploy documentation` job reuses it to push to `gh-pages`.

Do not replace `GH_TOKEN` with `secrets.GITHUB_TOKEN` without first granting the Actions bot a branch-protection bypass on `main`; otherwise checkout succeeds and the release fails later at the push.

The token expires. When it does, the whole main pipeline goes red and the `Verify release credentials` step names the failure (`HTTP 401`). To recover, mint a replacement with `contents: write` on this repository — plus permission to bypass the protection on `main` — and update the `GH_TOKEN` repository secret under **Settings → Secrets and variables → Actions**. Re-run the failed workflow to confirm.

## Further Reading
- [CLAUDE.md](CLAUDE.md) — architecture: dependency flow, container categories, config/env layering, mount assembly, and the scaffold system.
- [README.md](README.md) — project overview, command reference, and the release/branch model (branch-to-publish mapping).
- [TMUX.md](TMUX.md) — runbook for the multi-pane `ai-shell claude --multi` workflow.
