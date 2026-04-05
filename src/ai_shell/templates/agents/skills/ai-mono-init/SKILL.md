---
name: ai-mono-init
description: First-time monorepo development setup. Initializes submodules and verifies environment. Use when setting up a monorepo for development or saying 'set up this monorepo'.
argument-hint: "[--submodule <name>]"
---

Set up this monorepo for development: $ARGUMENTS

Initializes all submodules, verifies tracked branches are configured in `.gitmodules`, checks .env files, and guides per-submodule AI tool setup.

## Usage Examples
- `/ai-mono-init` - Full first-time setup
- `/ai-mono-init --submodule backend` - Check one submodule only

## 1. Run Init

```bash
ai-mono init --json $ARGUMENTS
```

If `ai-mono` is not found, install it: `uv sync --all-extras`, then retry.

**JSON response:**
```json
{
  "submodules": [
    {"name": "str", "tracked_branch": "str", "branch_configured": true, "env_status": "ok|missing|no_template"}
  ],
  "warnings": ["str"],
  "deps_installed": true
}
```

## 2. Configure Unconfigured Branches

For each submodule where `branch_configured` is false, look inside the submodule directory to detect its type, then suggest the correct tracked branch:

- **IaC / backend / web service**: has `*.tf` files, `Dockerfile`, `docker-compose.yml`, `serverless.yml`, or deployment configs → suggest tracking `dev` (these use a dev-to-main promotion workflow)
- **Library / package**: has `pyproject.toml` with `[build-system]`, or `package.json` with a `main` field → suggest tracking `main` (libraries release directly from main)
- **Unknown**: ask the user which branch this submodule releases from

Explain to the user in plain terms: "The tracked branch tells the monorepo which branch to follow for updates. Backend services typically use 'dev' because changes go through staging first. Libraries use 'main' because they publish directly."

Set the branch:
```bash
git config -f .gitmodules submodule.<name>.branch <branch>
```

After setting all branches, stage and commit:
```bash
git add .gitmodules
git commit -m "chore: set tracked branches for submodules"
```

## 3. Fix Environment Files

For each submodule where `env_status` is:
- `missing` (has .env.example but no .env): `cp <submodule>/.env.example <submodule>/.env`
- `no_template`: note that no .env may be needed, or ask the user

Also check root .env if warnings mention it.

## 4. Report Setup Status

Format results as:

```
Monorepo setup complete!

Submodules initialized:
  - backend (tracks dev)
  - frontend (tracks dev)
  - shared-lib (tracks main)

Environment:
  - [OK] Root .env
  - [OK] backend/.env
  - [WARN] frontend/.env -- needs setup (see frontend/.env.example)

Next steps:
  1. Fix any .env warnings above
  2. Set up AI tools in each submodule:
     cd backend && ai-shell init --iac --all
     cd frontend && ai-shell init --iac --all
     cd shared-lib && ai-shell init --lib --all
  3. Check monorepo status: /ai-mono-status
```

Use the repo type detection from step 2 to suggest `--iac` vs `--lib` for each submodule:
- `--iac` for backends, web services, and infrastructure (repos that deploy)
- `--lib` for libraries and packages (repos that publish)

This is a one-time setup. After init, use `/ai-mono-status` for ongoing monitoring.

## Error Handling
- **Not a monorepo**: CLI exits with error -- relay the message
- **Submodule clone fails**: Suggest checking SSH keys / access
- **Specified submodule not found**: CLI exits with error -- relay and list available submodules
