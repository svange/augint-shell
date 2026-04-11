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

- Use `uv run ai-tools repo ...` for normal repo workflows (status, issues, branch prep, submit, CI, promote/rollback where applicable).
- Use `uv run ai-tools standardize <path> --verify --json` to check drift and `--all` to apply all standards; use `--area <area>` to target a single section.
- Do not use workspace-only `uv run ai-tools workspace ...` commands for single-repo service work.
