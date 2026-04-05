---
name: ai-mono-init
description: First-time monorepo development setup. Initializes submodules and verifies environment. Use when setting up a monorepo for development or saying 'set up this monorepo'.
argument-hint: ""
---

Set up this monorepo for development: $ARGUMENTS

Initializes all submodules, verifies tracked branches are configured in `.gitmodules`, checks .env files, and guides the user through per-submodule AI tool setup.

## Usage Examples
- `/ai-mono-init` - Full first-time setup

## 1. Verify Monorepo

```bash
if [ ! -f .gitmodules ]; then
    echo "ERROR: No .gitmodules found. This does not appear to be a monorepo."
    exit 1
fi
```

## 2. Initialize Submodules

```bash
git submodule update --init --recursive
```

Report which submodules were initialized.

## 3. Verify Tracked Branches

Each submodule should have a `branch` configured in `.gitmodules` so that `/ai-mono-sync` knows which branch to track. IaC repos with a dev-to-main workflow should track `dev`; library repos should track `main`.

```bash
NEEDS_BRANCH_CONFIG=()
for SUBMODULE in $(git submodule status | awk '{print $2}'); do
    BRANCH=$(git config -f .gitmodules "submodule.${SUBMODULE}.branch" 2>/dev/null)
    if [ -z "$BRANCH" ]; then
        NEEDS_BRANCH_CONFIG+=("$SUBMODULE")
        echo "[WARN] $SUBMODULE: no branch set in .gitmodules"
    else
        echo "[OK] $SUBMODULE: tracks $BRANCH"
    fi
done
```

If any submodules are missing branch config, guide the user:

```
The following submodules have no tracked branch in .gitmodules:
  - frontend
  - shared-lib

Set the branch each submodule should track:
  - IaC repos (dev-to-main workflow): git config -f .gitmodules submodule.frontend.branch dev
  - Library repos (main-only):        git config -f .gitmodules submodule.shared-lib.branch main

Then commit the change:
  git add .gitmodules && git commit -m "chore: set tracked branches for submodules"
```

Ask the user which branch each unconfigured submodule should track, then run the `git config -f .gitmodules` commands and commit.

## 4. Verify Environment Files

For each submodule, check for `.env`:

```bash
for SUBMODULE in $(git submodule status | awk '{print $2}'); do
    if [ -f "$SUBMODULE/.env" ]; then
        echo "[OK] $SUBMODULE/.env exists"
    elif [ -f "$SUBMODULE/.env.example" ]; then
        echo "[WARN] $SUBMODULE/.env missing -- copy from .env.example:"
        echo "  cp $SUBMODULE/.env.example $SUBMODULE/.env"
    else
        echo "[WARN] $SUBMODULE has no .env or .env.example"
    fi
done
```

Also check the monorepo root:
```bash
if [ -f ".env" ]; then
    echo "[OK] Monorepo root .env exists"
elif [ -f ".env.example" ]; then
    echo "[WARN] Root .env missing -- copy from .env.example"
else
    echo "[INFO] No .env at monorepo root (may not be needed)"
fi
```

## 5. Check Dev Dependencies

If the monorepo root has a `pyproject.toml`:
```bash
if [ -f "pyproject.toml" ]; then
    echo "Installing monorepo dev dependencies..."
    uv sync
fi
```

## 6. Report Setup Status

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

## Error Handling
- **Not a monorepo**: Clear error
- **Submodule clone fails**: Report which submodule failed, suggest checking SSH keys / access
- **uv not available**: Skip dependency install, suggest installing uv
