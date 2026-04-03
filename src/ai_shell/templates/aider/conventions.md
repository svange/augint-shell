# Project Conventions

## Critical Rules

- **No rebase on main**: NEVER use `git pull --rebase` or `git rebase` on the default branch. Use merge commits only.
- **No manual versioning**: NEVER manually edit version numbers. Semantic Release manages versions via conventional commits.
- **No lock file edits**: NEVER manually edit lock files (uv.lock, package-lock.json, poetry.lock, yarn.lock).
- **No .env commits**: NEVER commit .env files. Use .env.example for templates.
- **No force push to main**: NEVER use `git push --force` on main or the default branch.

## Commit Messages

- Conventional commits required: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
- Semantic versioning: `fix:` = patch, `feat:` = minor, `feat!:` = major
- Keep the first line under 72 characters
- Reference issues with `Refs #N` or `Closes #N`

## Branch Naming

- `{type}/issue-N-description` where type is: feat, fix, docs, refactor, test, chore, ci, build, style, revert, perf

## Code Style

- Follow existing patterns in the codebase
- Run `uv run pre-commit run --all-files` explicitly before committing (no automatic git hooks)
- If pre-commit checks fail, fix and create a new commit (do not amend)

## Development Commands

```bash
uv sync --all-extras                         # Install dependencies
uv run pytest                                # Run tests
uv run ruff check src/                       # Lint
uv run mypy src/                             # Type check
uv run pre-commit run --all-files            # Pre-commit hooks
```

## Testing

- All new features require unit tests
- Bug fixes should include a regression test
- Maintain test coverage above project threshold
