# Project Notes

<!-- Project-specific notes for AI coding agents. This file is created
     once by ai-shell and NEVER overwritten or deleted by scaffold
     operations (--update, --clean). Each agent's /init reads this file
     and integrates it into the appropriate config (CLAUDE.md, AGENTS.md,
     CONVENTIONS.md). -->

## Monorepo Overview

<!-- Describe what this monorepo coordinates and the overall system architecture. -->

## Submodule Map

<!-- List each submodule, its purpose, tracked branch, and repo URL.

| Submodule  | Purpose    | Tracks | Stack          | Repo                          |
|------------|------------|--------|----------------|-------------------------------|
| backend    | API server | dev    | Python/FastAPI | github.com/org/backend        |
| frontend   | Web UI     | dev    | TypeScript/React | github.com/org/frontend     |
| shared-lib | Shared utils | main | Python         | github.com/org/shared-lib     |

Tracked branches are configured in `.gitmodules`. IaC repos with a dev-to-main
workflow should track `dev`; library repos should track `main`. Set with:
  git config -f .gitmodules submodule.<name>.branch <branch>
-->

## Critical Rules

- **No rebase on main**: NEVER use `git pull --rebase` or `git rebase` on the default branch. Use merge commits only.
- **No .env commits**: NEVER commit .env files. Use .env.example for templates.
- **No force push to main**: NEVER use `git push --force` on main or the default branch.
- **No cross-boundary edits**: NEVER modify files inside submodules from the monorepo root. Always `cd` into the submodule to make changes using that submodule's own tooling and context.
- **Commit pointer changes deliberately**: Submodule pointer updates should be intentional, never accidental side effects of other work.

## Working in This Monorepo

### When to work at monorepo level (this directory)
- Cross-repo status and coordination: `/ai-mono-status`
- Syncing submodule pointers: `/ai-mono-sync`
- Cross-repo health analysis: `/ai-mono-health`
- Editing monorepo-level docs, tools, and configs
- Managing submodule relationships

### When to work inside a submodule
- All code development, bug fixes, and feature work
- Running tests, linting, and type checking
- Creating PRs and monitoring pipelines
- Each submodule has its own `.env`, `ai-shell.toml`, and AI tool configs

### Switching context
```bash
cd backend/                  # Enter submodule for development work
ai-shell claude              # Launches with backend's .env and context
cd ..                        # Return to monorepo root for coordination
```

## Environment Setup

Each directory level has its own `.env` file:
- **Monorepo root `.env`**: GH_TOKEN for cross-repo operations, shared service tokens
- **Submodule `.env`**: Deployment credentials, environment-specific variables

These are independent -- ai-shell loads `.env` from the current working directory only.

## Monorepo Coordination Tools

This monorepo uses `ai-mono` for coordination across submodules:

```bash
uv run ai-mono status    # Cross-repo status dashboard
uv run ai-mono sync      # Update submodule pointers
uv run ai-mono init      # First-time dev setup
uv run ai-mono health    # Cross-repo health analysis
uv run ai-mono foreach   # Run command in each submodule
# All commands support: --json (structured output), -s/--submodule <name> (filter)
```

## Conventions

- **Commits**: Conventional commits required. `fix:` = patch, `feat:` = minor, `feat!:` / `BREAKING CHANGE` = major.
- **Branches**: `{type}/issue-N-description` where type is one of: feat, fix, docs, refactor, test, chore, ci, build, style, revert, perf.
- **Submodule updates**: Use `chore(deps):` prefix for submodule pointer update commits.

## Development Workflow

1. **First-time setup** (once): `/ai-mono-init` -- initializes submodules, verifies branch config and .env files
2. **Check status**: `/ai-mono-status` -- see what is happening across all repos
3. **Sync pointers**: `/ai-mono-sync` -- ensure submodule pointers are current
4. **Pick work**: Identify which submodule needs attention, `cd` into it
5. **Develop**: Follow that submodule's own workflow (pick issue, prepare branch, develop, submit)
6. **Update pointers**: Return to monorepo root, `/ai-mono-sync` to capture merged work

Only sync pointers after PRs are merged in the submodule. Syncing while feature branches are in progress can cause confusion.

## Key Concepts

When explaining submodule state to users, use plain language:

- **Submodule pointer**: the monorepo records which exact version (commit) of each submodule it uses. "Stale pointer" means the submodule has newer work that hasn't been picked up yet.
- **Tracked branch**: the branch in each submodule that the monorepo follows for updates (configured in `.gitmodules`). IaC/backend repos typically track `dev`; libraries track `main`.
- **Syncing**: updating the monorepo to use the latest version of each submodule's tracked branch.

## Common Problems and Recovery

### Accidental pointer change
If `git status` shows an unexpected submodule change you didn't intend:
```bash
git restore <submodule-path>    # Undo the pointer change
```

### Submodule shows "modified content" or merge conflicts
You (or the AI agent) edited files inside a submodule from the monorepo root. Fix by working inside the submodule:
```bash
cd <submodule>
git status                      # See what changed
git stash                       # Or commit/discard as appropriate
cd ..
```

### Submodule not initialized or missing
```bash
/ai-mono-init                   # Re-initializes all submodules
```

### Pointer sync fails due to local changes in submodule
```bash
cd <submodule>
git stash                       # Save local work
cd ..
/ai-mono-sync --commit          # Now sync will succeed
cd <submodule>
git stash pop                   # Restore local work
```

## Batch Operations vs Manual Work

Use `/ai-mono-foreach` for **read-only checks** across all submodules:
- `git status`, `uv run pytest`, dependency audits, standards checks

Use **manual `cd` into each submodule** for **development work**:
- Code changes, dependency updates, branch management, PR creation
- The "no cross-boundary edits" rule means development always happens inside a submodule

## Architecture

<!-- High-level system architecture showing how submodules relate to each other -->

## Cross-Repo Conventions

<!-- Shared dependency version policy, API contract locations, inter-service communication patterns -->

## Notes

<!-- Anything else an AI agent should know about this monorepo -->
