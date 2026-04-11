# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A multi-product ecosystem for a health insurance brokerage, decomposed from a legacy monolith (`reference/hwh-work/`). Each sub-directory is an independent product with its own git repo, AWS account, CI/CD, and tech stack. This root repo orchestrates development across all products.

## Project Map

| Project | Stack | IaC | Status | URL |
|---------|-------|-----|--------|-----|
| **woxom-common** | Python (pydantic) + Node (TypeScript) | None (library) | Planned | PyPI + npm |
| **woxom-crm** | Next.js 16, React 19, Zustand | SAM | Frontend only | crm.woxomhealth.com |
| **woxom-data-parser** | Python 3.12, Flask/Mangum | CDK | Deployed | convert.woxomhealth.com |
| **woxom-infra** | SAM templates | SAM (no CDK) | Planned | auth.woxomhealth.com |
| **woxom-quoting-tool** | Node.js 20, Vanilla JS, esbuild | CDK (5 stacks) | Deployed | quotes.woxomhealth.com |
| **woxom-sales-dashboard** | Python 3.12 FastAPI + React/Vite | CDK (6 stacks) | Deployed | dashboard.woxomhealth.com |
| **woxom-health-web** | React/Vite + Lambda (npm workspaces) | CDK (2 stacks) | Partial | woxomhealth.com |
| **woxom-visualization** | React 19, React Flow, ELK.js, Vite | None (dev tool) | Extracted | localhost:3001 |

## Dependency Flow

```
woxom-infra (Cognito, SES, DNS) ← all products authenticate against this
woxom-common (AV calc, agent normalization, JWT middleware) ← all products consume this
```

**Duplicated business logic needing extraction to woxom-common:**
- AV calculation: source of truth is `woxom-data-parser/shared/business_logic.py`, duplicated in `woxom-sales-dashboard/lambda_/deal_ingest.py`
- Agent name normalization (AGENT_MERGES): duplicated across data-parser and sales-dashboard
- Cognito JWT validation: reference impl at `reference/hwh-work/reference-repos/ai-lls-api/src/auth_authorizer.py`

## Development Commands

Each sub-project has its own CLAUDE.md with project-specific commands. Common patterns:

```bash
# Python projects (data-parser, sales-dashboard, common)
uv sync --all-extras                         # Install dependencies
uv run pytest                                # Run tests
uv run pytest --cov=src --cov-fail-under=80  # Tests with coverage
uv run ruff check src/                       # Lint
uv run mypy src/                             # Type check
uv run pre-commit run --all-files            # All pre-commit hooks

# Node projects (quoting-tool, crm, health-web)
npm install                                  # Install dependencies
npm test                                     # Run tests (vitest)
npm run build                                # Build
npm run lint                                 # Lint (eslint)
```

## Critical Rules

- **No rebase on main** -- NEVER use `git pull --rebase` or `git rebase` on the default branch. Use merge commits only.
- **No manual versioning** -- semantic-release via conventional commits (`fix:` = patch, `feat:` = minor, `feat!:` / `BREAKING CHANGE` = major)
- **No lock file edits** -- NEVER directly write text into lock files (uv.lock, package-lock.json, poetry.lock, yarn.lock). Always use package manager commands (`uv lock`, `uv add`, `npm install`) to regenerate them. When a package manager command updates a lock file, ALWAYS stage and include it in the commit -- lock file changes must never be left uncommitted.
- **Tests required** -- write tests for all new functionality; bug fixes require regression tests
- **No .env commits** -- use `.env.example` for templates
- **No force push to main**
- **Pre-commit hooks must be run explicitly** (`uv run pre-commit run --all-files`) -- git hooks are disabled because they break across Windows/WSL. If checks fail, fix the issue and create a NEW commit (do not amend).
- **IaC varies by project**: woxom-infra and woxom-crm use SAM; data-parser, quoting-tool, sales-dashboard, health-web use CDK
- **woxom-infra must never use CDK** -- SAM only

## Branch and Workflow Conventions

- Branch naming: `{type}/issue-N-description` (feat, fix, docs, refactor, test, chore, ci, build, style, revert, perf)
- PRs target the default development branch with automerge enabled
- `dev` branch deploys to staging; `main` deploys to production
- Staging domains: `*.aillc.link`; Production domains: `*.woxomhealth.com`
- AWS profiles: `woxom-staging` and `woxom-prod`; region is always `us-east-1`

## Development Workflow

**IMPORTANT**: Always follow this sequence. Do NOT skip to step 3 without completing step 2 first.

1. **Pick an issue**: `/ai-pick-issue` -- find or get assigned work
2. **Prepare branch**: `/ai-prepare-branch` -- REQUIRED before any code changes. Creates a fresh branch from the latest base (main or dev), syncs upstream, sets up remote tracking. Never start coding on an existing branch from a previous task.
3. **Develop**: Write code with tests, following project conventions
4. **Submit**: `/ai-submit-work` -- runs all checks locally, commits, pushes, creates automerge PR
5. **Monitor**: `/ai-monitor-pipeline` -- watches CI, diagnoses failures, auto-fixes and re-pushes

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

## Workspace Workflow

This repo is a workspace coordination layer. Product code changes land in child repos, not here. The top-level agent reasons across all repos, but validation and PR submission remain repo-specific.

**Initialize**: `/ai-workspace-sync` clones all child repos from `workspace.yaml`.

**Status**: `/ai-workspace-status` shows branches, dirty state, PRs, CI across all repos.

**Develop**: Use workspace skills for cross-repo orchestration:
- `/ai-workspace-pick` -- find issues across repos
- `/ai-workspace-branch` -- create coordinated branches
- `/ai-workspace-test` -- run tests in dependency order
- `/ai-workspace-submit` -- push and open PRs per repo
- `/ai-workspace-update` -- propagate dependency changes downstream

**CLI commands** (underlying the skills above):
```bash
uv run ai-tools workspace sync --json       # Materialize/refresh child repos
uv run ai-tools workspace status --json     # Actionable workspace snapshot
uv run ai-tools workspace issues            # Cross-repo issue aggregation
uv run ai-tools workspace branch            # Coordinated branch creation
uv run ai-tools workspace check --phase tests|quality --json  # Coordinated validation
uv run ai-tools workspace submit            # Cross-repo PR submission
uv run ai-tools workspace update            # Propagate dependency changes
uv run ai-tools workspace foreach           # Run a command across child repos
```

**Typical flow**: sync -> status -> issue selection -> coordinated branch prep -> develop repo-by-repo -> validate -> submit.

**Standardization**: Run `uv run ai-tools standardize ...` inside each child repo individually. Keep workspace planning in `workspace`; keep standards detection/fixes in `standardize`.

**Agent behavior**: The top-level agent owns cross-repo planning. Use subagents only for bounded parallel work or adversarial review. Respect per-repo target branches from `workspace.yaml` instead of guessing.

**Policy**: Keep cross-repo orchestration separate from repo-local implementation rules. Open PRs per affected repo and preserve repo-specific release and promotion rules.

## Architecture Notes

- **Separate AWS accounts** per product, plus a shared-infrastructure account for woxom-infra
- **Cognito** is the universal auth layer (single user pool in woxom-infra, per-product app clients)
- **DynamoDB single-table design** is used by quoting-tool, sales-dashboard, crm, and health-web
- **Sales dashboard multi-instance**: HWH and Jackson Healthcare share the same DynamoDB table, partitioned by `INST#` prefix, Eastern timezone only
- **Quoting tool plan IDs are mixed types** (numeric for LifeX, string for others) -- never use `parseInt()`
- **GoHighLevel CRM integration** in health-web encrypts credentials with KMS before DynamoDB storage
- **reference/hwh-work/** is the legacy monolith being decomposed -- use it as source of truth when extracting logic but never deploy from it
- **Compass_CRM** (from reference/hwh-work/) is archived -- replaced by woxom-crm
