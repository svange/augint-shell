# Institutional Notes: Service Repos

These notes extend the shared institutional notes for service, web, API, and IaC repositories.
Merge them lightly and only when they add net-new guidance.

## Branch and Merge Policy

- Service-style repos usually branch from and target a development branch first.
- Promotion from the development branch to `main` should use merge commits.
- If the repo is treated as IaC, merge-commit-only policy applies; do not squash promotions.
- Do not rebase the default branch.

## Development Flow

- Standard flow: pick issue -> prepare branch -> develop -> submit -> monitor.
- Use promotion workflows only after staging or development validation is complete.
- Keep deployment and release rules repo-specific; do not invent them during implementation.

## `ai-tools` Usage

- Use `ai-tools init` for workflow bootstrap.
- Use normal repo commands at the root level, not under `mono`.
