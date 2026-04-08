# Landline Scrubber Workspace

Phone number verification SaaS workspace for coordinated development across:

| Repo | Description | Stack |
|------|-------------|-------|
| `ai-lls-lib` | Core business logic library | Python 3.12, PyPI |
| `ai-lls-api` | AWS Lambda REST API | Python 3.12, SAM |
| `ai-lls-web` | Frontend UI | Vue 3, Vite, CloudFront |

This repository is a coordination workspace, not a repo-bundling repository.
The child repos are cloned into `repos/` and are intentionally not tracked by this repo.

## Why This Model

Submodules are good for pinning exact integration commits. They are poor for daily
agentic development because they add detached HEADs, pointer commits, and friction
when one task spans multiple repos.

This workspace model keeps each product repo independent while giving Codex/Claude
one place to coordinate cross-repo work.

## Quick Start

```bash
git clone https://github.com/Augmenting-Integrations/landline-scrubber.git
cd landline-scrubber

# Install workspace tooling
uv sync

# Planned workflow once augint-tools grows workspace support:
augint-tools sync
augint-tools status
```

## Layout

```text
landline-scrubber/
  workspace.toml          # Repo manifest for the workspace
  repos/                  # Ignored local clones
    ai-lls-lib/
    ai-lls-api/
    ai-lls-web/
```

## Target Commands

```bash
augint-tools sync                               # Clone missing repos, fetch existing ones
augint-tools status                             # Branch / dirty / PR / CI / alignment status
augint-tools issues                             # Aggregate issues across repos
augint-tools branch feat/issue-42-x --repos ai-lls-lib ai-lls-api
augint-tools test --repos ai-lls-lib ai-lls-api
augint-tools lint --repos ai-lls-lib ai-lls-api --fix
augint-tools submit --repos ai-lls-lib ai-lls-api
augint-tools update --from ai-lls-lib
```

These commands are the intended steady-state workflow. This repo tracks that design
and its AI skills assume those commands will be provided by `augint-tools`.

## How To Work

### Single-repo change

```bash
cd repos/ai-lls-api
ai-shell codex
```

Use the repo's own tooling, tests, PR flow, and release process.

### Cross-repo change

```bash
cd /path/to/landline-scrubber
ai-shell codex
```

From the workspace root, the agent can inspect all repos, create matching
branches with `augint-tools branch ...`, and tell you which repo to enter when
repo-specific validation or submission is needed.

## Recommended AI Workflow

1. Use the workspace root for coordination, design changes, and cross-repo analysis.
2. Use `augint-tools sync` to ensure the repo set is present and current.
3. Use `augint-tools status` or `/ai-workspace-status` to see branch, PR, CI, and dependency state.
4. Use `augint-tools issues` or `/ai-workspace-pick` to choose work across repos.
5. Create matching branches across affected repos with `augint-tools branch ...`.
6. Launch one AI session from the workspace root and implement repo-by-repo in dependency order.
7. Use `augint-tools test` and `augint-tools lint` for cross-repo validation.
8. Use `augint-tools submit` to push and open PRs in each affected repo.
9. After upstream changes land, use `augint-tools update` for downstream dependency bumps.

By default, target `main` for libraries and `dev` for service/web/IaC repos unless
the workspace manifest says otherwise.

## Deployment Order

1. `ai-lls-lib` publishes to PyPI
2. `ai-lls-api` deploys Lambda + API Gateway
3. `ai-lls-web` builds and deploys using API outputs
