---
name: ai-mono-status
description: Cross-repo status dashboard showing PRs, issues, pipelines, and submodule pointer state across all submodules. Use when asking 'what is happening across repos' or 'monorepo status'.
argument-hint: "[--submodule <name>]"
---

Show cross-repo status across all submodules in this monorepo: $ARGUMENTS

Provides a unified view of work happening across all submodules: open PRs, pipeline status, submodule pointer freshness, and suggested next actions.

## Usage Examples
- `/ai-mono-status` - Full status across all submodules
- `/ai-mono-status --submodule backend` - Status for one submodule only

## 1. Detect Submodules

```bash
# Verify this is a monorepo (has .gitmodules)
if [ ! -f .gitmodules ]; then
    echo "ERROR: No .gitmodules found. This does not appear to be a monorepo."
    echo "Run this command from the monorepo root directory."
    exit 1
fi

git submodule status --recursive
```

Parse each submodule: name, current SHA, path.

## 2. Resolve Tracked Branch Per Submodule

Each submodule tracks a specific branch configured in `.gitmodules`. IaC repos with a dev-to-main workflow should track `dev`; library repos track `main`.

```bash
# Read the tracked branch from .gitmodules (falls back to remote HEAD, then "main")
tracked_branch_for() {
    local sub="$1"
    # 1. Check .gitmodules branch setting
    local branch
    branch=$(git config -f .gitmodules "submodule.${sub}.branch" 2>/dev/null)
    if [ -n "$branch" ]; then
        echo "$branch"
        return
    fi
    # 2. Fall back to the submodule's remote HEAD
    branch=$(cd "$sub" && git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')
    if [ -n "$branch" ]; then
        echo "$branch"
        return
    fi
    # 3. Default to main
    echo "main"
}
```

## 3. Per-Submodule Status

For each submodule:

```bash
SUBMODULE="backend"  # example
TRACKED=$(tracked_branch_for "$SUBMODULE")

# Current pointer vs tracked branch HEAD
POINTER_SHA=$(git submodule status "$SUBMODULE" | awk '{print $1}' | tr -d '+\-U')
cd "$SUBMODULE"
git fetch --all --prune 2>/dev/null

REMOTE_SHA=$(git rev-parse "origin/$TRACKED" 2>/dev/null)

# Commits behind
if [ "$POINTER_SHA" != "$REMOTE_SHA" ]; then
    BEHIND=$(git log --oneline "$POINTER_SHA..$REMOTE_SHA" 2>/dev/null | wc -l)
    echo "$SUBMODULE: $BEHIND commits behind origin/$TRACKED"
else
    echo "$SUBMODULE: up to date (tracking $TRACKED)"
fi

# Open PRs
gh pr list --state open --json number,title,author,updatedAt --limit 5

# Latest CI run
gh run list --limit 1 --json status,conclusion,name,createdAt

cd ..
```

## 4. Aggregated Dashboard

Format output as a table:

```
Monorepo Status
===============

| Submodule | Tracks | Pointer  | Behind | Open PRs | CI Status |
|-----------|--------|----------|--------|----------|-----------|
| backend   | dev    | a1b2c3d  | 3      | 2        | passing   |
| frontend  | dev    | d4e5f6g  | 0      | 1        | failing   |
| shared-lib| main   | h7i8j9k  | 1      | 0        | passing   |

Summary:
  - 3 open PRs across all submodules
  - 1 submodule with failing CI (frontend)
  - 2 submodules with stale pointers
```

## 5. Suggested Next Actions

Based on status, suggest:
- If submodules are behind: "Run `/ai-mono-sync` to update pointers"
- If CI is failing: "Check frontend: `cd frontend && /ai-monitor-pipeline`"
- If PRs need review: List them with links
- If a submodule has no `branch` set in `.gitmodules`: "Consider setting tracked branch: `git config -f .gitmodules submodule.backend.branch dev`"
- If everything is clean: "All submodules are up to date. No action needed."

## Error Handling
- **Not a monorepo**: Clear error pointing to monorepo root
- **Submodule not initialized**: Suggest `git submodule update --init`
- **No GitHub remote**: Skip PR/CI checks for that submodule, warn
- **Rate limiting**: Warn and show partial results
