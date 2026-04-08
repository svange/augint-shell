# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Landline Scrubber is a workspace repo for coordinated development across three independent repositories:

| Repo | Stack | Purpose |
|-----------|-------|---------|
| `ai-lls-lib` | Python 3.12, PyPI | Shared business logic library (PhoneVerifier, BulkProcessor, DynamoDB cache, Stripe/credit management) |
| `ai-lls-api` | Python 3.12, AWS SAM/Lambda | Thin REST API handlers -- orchestration only, all logic delegates to ai-lls-lib |
| `ai-lls-web` | Vue 3, Vite, S3+CloudFront | Frontend UI -- no business logic, calls API endpoints |

The child repos are local clones under `repos/` and are not tracked by this repo.
Each child repo has its own instructions. Read them before editing there.
This workspace is expected to use `augint-tools` as the orchestration tool.

## Development Commands

### Python repos (ai-lls-api, ai-lls-lib)

```bash
cd repos/ai-lls-api  # or repos/ai-lls-lib
uv sync --all-extras                         # Install dependencies
uv run pytest -m "unit" -v                   # Unit tests only
uv run pytest tests/unit/test_foo.py -v      # Single test file
uv run pytest tests/unit/test_foo.py::test_bar -v  # Single test
uv run pytest --cov=src --cov-fail-under=80  # Coverage (80% minimum)
uv run ruff check src/                       # Lint
uv run mypy src/                             # Type check (disallow_untyped_defs)
uv run pre-commit run --all-files            # All pre-commit hooks
```

### Frontend (ai-lls-web)

```bash
cd repos/ai-lls-web
npm ci                    # Install dependencies
npm run dev               # Dev server (port 5173)
npm run build             # Production build
npm run test              # Unit tests (Vitest)
npm run test:e2e          # E2E tests (Playwright, requires staging)
npm run lint              # ESLint
npm run format            # Prettier
npm run type-check        # vue-tsc
```

### API build and deploy (ai-lls-api)

```bash
make build-layer    # Build Lambda dependency layer (~424MB)
make build-all      # Layer + SAM build
sam deploy --guided # Deploy
```

## Architecture

```
User -> CloudFront (ai-lls-web) -> API Gateway v2 -> Lambda handlers (ai-lls-api) -> ai-lls-lib
                                                                                    -> DynamoDB (cache, credits, API keys)
                                                                                    -> S3 (bulk file storage)
                                                                                    -> SQS (bulk processing queue + DLQ)
                                                                                    -> landlineremover.com API
                                                                                    -> Stripe
```

**Auth**: Cognito JWT (`Authorization: Bearer`) or API key (`X-LLS-Key` header). Authorizer returns IAM policy format with string context values (`"true"`/`"false"`, not booleans).

**Deployment order matters**: ai-lls-lib (PyPI) -> ai-lls-api (creates Cognito, API Gateway) -> ai-lls-web (fetches CloudFormation outputs for build-time env vars).

## Critical Rules

- **No rebase on main**: NEVER use `git pull --rebase` or `git rebase` on the default branch. Use merge commits only. Rebase on main breaks CI and semantic-release.
- **No manual versioning**: NEVER manually edit version numbers. Semantic Release owns versions via conventional commits. Tags: `ai-lls-lib-v{version}`, `landline-api-v{version}`.
- **No lock file edits**: NEVER directly write text into lock files (uv.lock, package-lock.json, poetry.lock, yarn.lock). Always use package manager commands (`uv lock`, `uv add`, `npm install`) to regenerate them. When a package manager command updates a lock file, ALWAYS stage and include it in the commit -- lock file changes must never be left uncommitted.
- **No .env commits**: NEVER commit .env files. Use `.env.example` for templates.
- **No force push to main**: NEVER use `git push --force` on main or the default branch.
- **Pre-commit**: Run `uv run pre-commit run --all-files` explicitly before committing (no automatic git hooks -- they break across Windows/WSL). If checks fail, fix and create a NEW commit (do not amend).

## Branch and Merge Strategy

- **Branch naming**: `{type}/issue-N-description` (types: feat, fix, docs, refactor, test, chore, ci, build, style, revert, perf)
- **Feature PRs target `dev`**, merged with `--squash`. Enable automerge
- **dev -> main promotion PRs** use `--merge` (NOT `--squash`) -- squash merges concatenate commit messages and semantic-release's `[skip ci]` silently kills the production deploy pipeline
- **After production deploy**: sync dev back from main (`git checkout dev && git merge main`)
- **Conventional commits**: `fix:` = patch, `feat:` = minor, `feat!:` / `BREAKING CHANGE` = major

## Code Style

- **Python**: Ruff (line-length 100, Google docstrings), MyPy with `disallow_untyped_defs: true`, target Python 3.12
- **JavaScript**: ESLint + Prettier, Vue 3 accessibility rules, type checking via vue-tsc
- **Pre-commit hooks**: gitleaks (secret detection), ruff-format, ruff-check, mypy, forbid-env-commit

## Key Design Constraints

- **Lambda handlers are thin**: Parse event, call ai-lls-lib service, format response. All business logic in ai-lls-lib.
- **Module-level imports only**: Lambda INIT phase. Never import inside handler functions. Use lazy-init pattern for secrets.
- **No mock data in production**: If external services fail, return proper HTTP errors (503). Mock data belongs only in tests.
- **Frontend is UI only**: No business logic duplication. All validation and rules live in the API.
- **Test patching**: In ai-lls-api tests, import handlers INSIDE test functions AFTER patches are applied (module-level init would make real AWS calls).
- **Test coverage**: Write tests for all new functionality. Bug fixes require regression tests.

## Development Workflow

**IMPORTANT**: Always follow this sequence. Do NOT skip to step 3 without completing step 2 first.

1. **Pick an issue**: `/ai-pick-issue` -- find or get assigned work
2. **Prepare branch**: `/ai-prepare-branch` -- REQUIRED before any code changes. Creates a fresh branch from the latest base (main or dev), syncs upstream, sets up remote tracking. Never start coding on an existing branch from a previous task.
3. **Develop**: Write code with tests, following project conventions
4. **Submit**: `/ai-submit-work` -- runs all checks locally, commits, pushes, creates automerge PR
5. **Monitor**: `/ai-monitor-pipeline` -- watches CI, diagnoses failures, auto-fixes and re-pushes

## Deployment

- **dev branch** -> staging (www.lls.aillc.link)
- **main branch** -> production (www.landlinescrubber.com)
- **CI pipeline**: pre-commit -> security scan (Semgrep, Bandit, pip-audit) -> unit tests -> infra validation -> deploy

## Workspace Workflow (Cross-Cutting Changes)

For changes that touch multiple repos, use the workspace root and the `/ai-workspace-*` skills:

1. `/ai-workspace-sync` -- clone missing repos and fetch existing ones
2. `/ai-workspace-status` -- see overall system state
3. `/ai-workspace-pick` -- inspect issues across all repos and choose a task
4. `/ai-workspace-branch 42 --repos lib,api` -- create matching branches
5. Make changes in dependency order: lib -> api -> web
6. `/ai-workspace-test` -- validate across all repos
7. `/ai-workspace-lint --fix` -- fix quality issues
8. `/ai-workspace-submit` -- push and open PRs in each affected repo
9. `/ai-workspace-update` -- after lib release, update api dependency

Default submission policy:
- Libraries target `main`
- Services/web/IaC target `dev`
- The workspace manifest is the source of truth when configured

For single-repo work, use the standard workflow (`/ai-pick-issue`, `/ai-prepare-branch`, etc.) from within the real repo directory under `repos/`.

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

## Git Operation Scoping

Git commands apply to whichever `.git` repo you're in:
- **At root**: `git status` shows only the workspace repo (docs, tooling, manifest)
- **Inside `repos/<name>`**: `git status` shows that product repo's state

When working in a child repo, that repo's local instructions take precedence for module-specific rules.
One top-level AI session may still coordinate and edit across all repos from the workspace root.

## Virtualenv Isolation

- **Root `.venv`**: workspace tools only. Do NOT install app/lib dependencies here.
- **Each repo under `repos/`**: has its own environment. Run that repo's install command inside it.
- **Never share** one environment across all repos.
