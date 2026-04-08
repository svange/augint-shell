# Institutional Notes

These notes are shared workflow guidance for Augmenting Integrations repositories.
They are meant to be merged into agent context files during `--update` runs.
They are not a project summary template and should not displace repo-specific architecture or domain notes.

## Merge Behavior

- Merge this guidance lightly and idempotently.
- If equivalent guidance already exists in `CLAUDE.md` or `AGENTS.md`, leave it alone.
- Do not strengthen wording or repeat the same rule just because the merge runs again.
- Preserve project-specific instructions unless these notes clearly supersede them.

## Shared Workflow Rules

- Use merge commits only on `main` unless a repo-specific rule says otherwise.
- Never manually edit version numbers managed by semantic-release.
- Never hand-edit lock files; regenerate them with the package manager.
- Never commit `.env` files.
- Never force-push the default branch.
- Run `pre-commit` explicitly before committing when the repo uses it.
- Bug fixes require regression tests.

## Branch and PR Patterns

- Branch names follow `{type}/issue-N-description`.
- Conventional commits are required.
- Libraries generally target `main`.
- Service-style repos generally target their development branch, then promote via merge commit.
- When a service or IaC rule says "merge commits only", apply it literally and do not squash.

## AI Workflow Patterns

- Default normal-repo flow: pick issue -> prepare branch -> develop -> submit -> monitor.
- Use repo-local skills and commands for implementation work inside a single repo.
- Use `ai-tools` for standardized orchestration where available.
- Workspace orchestration commands now live under `ai-tools mono ...`.

## `ai-tools` Conventions

- Normal repo commands are rooted at `ai-tools <command>`.
- Workspace commands are rooted at `ai-tools mono <command>`.
- Prefer machine-readable output when available for agent consumption.
- Keep branch, PR target, and validation policy driven by repo or workspace config rather than guesswork.
