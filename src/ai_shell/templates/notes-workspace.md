# Institutional Notes: Workspaces

These notes extend the shared institutional notes for workspace repositories.
Merge them lightly and only when they add net-new guidance.

## Workspace Model

- A workspace is a coordination repo for multiple child repos.
- Product code changes land in child repos, not in the workspace coordination layer.
- The top-level agent may reason across all repos, but validation and PR submission remain repo-specific.

## `ai-tools mono` Conventions

- Workspace orchestration commands live under `ai-tools mono`.
- Use `ai-tools mono init` to bootstrap a workspace.
- Use `ai-tools mono sync` to materialize or update child repos.
- Use `ai-tools mono status`, `issues`, `branch`, `foreach`, `test`, `lint`, `submit`, and `update` for cross-repo orchestration.

## Workspace Flow

- Typical flow: sync -> status -> issue selection -> coordinated branch prep -> develop repo-by-repo -> validate -> submit.
- The top-level agent should normally own cross-repo planning.
- Use subagents only for bounded parallel work or adversarial review.
- Respect per-repo target branches from workspace config instead of guessing.

## Merge and Submission Policy

- Keep cross-repo orchestration separate from repo-local implementation rules.
- Open PRs per affected repo.
- Preserve repo-specific release and promotion rules.
