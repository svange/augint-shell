# Project Notes

<!-- Project-specific notes for AI coding agents. This file is created
     once by ai-shell and NEVER overwritten or deleted by scaffold
     operations (--update, --clean). Each agent's /init reads this file
     and integrates it into the appropriate config (CLAUDE.md, AGENTS.md,
     CONVENTIONS.md). -->

## Workspace Overview

<!-- Describe what this workspace coordinates and the overall system architecture. -->

## Repo Map

<!-- List each child repo, its purpose, tracked branch, and repo URL.

| Repo       | Purpose    | Tracks | Stack            | Repo                          |
|------------|------------|--------|------------------|-------------------------------|
| backend    | API server | dev    | Python/FastAPI   | github.com/org/backend        |
| frontend   | Web UI     | dev    | TypeScript/React | github.com/org/frontend       |
| shared-lib | Shared utils | main | Python           | github.com/org/shared-lib     |
-->

## Critical Rules

- **No rebase on main**: NEVER use `git pull --rebase` or `git rebase` on the default branch. Use merge commits only.
- **No .env commits**: NEVER commit .env files. Use .env.example for templates.
- **No force push to main**: NEVER use `git push --force` on main or the default branch.
- **No cross-boundary edits by accident**: Be explicit about which child repo you are editing and validate in that repo.

## Working in This Workspace

### When to work at workspace level (this directory)
- Cross-repo status and coordination
- Cross-repo issue selection and planning
- Editing workspace-level docs, tools, and configs
- Managing relationships between child repos

### When to work inside a child repo
- All code development, bug fixes, and feature work
- Running tests, linting, and type checking
- Creating PRs and monitoring pipelines
- Each child repo has its own `.env`, `ai-shell.toml`, and AI tool configs

### Switching context
```bash
cd backend/                  # Enter child repo for development work
ai-shell claude              # Launches with backend's .env and context
cd ..                        # Return to workspace root for coordination
```

## Environment Setup

Each directory level has its own `.env` file:
- **Workspace root `.env`**: GitHub and cross-repo coordination credentials
- **Child repo `.env`**: Deployment credentials, environment-specific variables

These are independent -- ai-shell loads `.env` from the current working directory only.

## Workspace Coordination Tools

This workspace uses `augint-tools` for cross-repo coordination:

```bash
augint-tools sync        # Ensure child repos are cloned and updated
augint-tools status      # Cross-repo status dashboard
augint-tools issues      # Aggregate issues across child repos
augint-tools branch      # Create coordinated branches
augint-tools test        # Run repo-specific tests
augint-tools lint        # Run repo-specific lint/quality checks
augint-tools submit      # Push and open PRs per repo
augint-tools update      # Propagate downstream dependency updates
```

## Conventions

- **Commits**: Conventional commits required. `fix:` = patch, `feat:` = minor, `feat!:` / `BREAKING CHANGE` = major.
- **Branches**: `{type}/issue-N-description` where type is one of: feat, fix, docs, refactor, test, chore, ci, build, style, revert, perf.

## Development Workflow

1. **First-time setup**: Use `/ai-init` and choose `workspace`
2. **Sync repos**: Use workspace tooling to ensure repos are present
3. **Check status**: Review what is happening across all child repos
4. **Pick work**: Identify which child repo(s) need attention
5. **Develop**: Follow each child repo's own workflow for implementation
6. **Validate and submit**: Run cross-repo validation, then submit PRs per child repo

## Key Concepts

- **Workspace repo**: coordination layer for multiple related repos
- **Child repo**: the actual implementation repo where code changes land
- **Cross-repo workflow**: planning and validation that spans multiple child repos

## Batch Operations vs Manual Work

Use workspace-level tooling for read-only checks and orchestration across all child repos.

Use manual `cd` into each child repo for code changes, dependency updates, branch management, and PR creation.

## Architecture

<!-- High-level system architecture showing how child repos relate to each other -->

## Cross-Repo Conventions

<!-- Shared dependency version policy, API contract locations, inter-service communication patterns -->

## Notes

<!-- Anything else an AI agent should know about this workspace -->
