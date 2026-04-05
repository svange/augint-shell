---
name: ai-mono-sync
description: Sync submodule pointers to latest tracked branch HEAD. Use when saying 'update submodules', 'sync repos', or 'update pointers'.
argument-hint: "[--commit] [--submodule <name>]"
---

Sync submodule pointers to their latest tracked branch HEAD: $ARGUMENTS

Updates submodule pointers to the latest commit on each submodule's tracked branch (configured in `.gitmodules`), optionally staging and committing the pointer changes.

## Usage Examples
- `/ai-mono-sync` - Show what would change (dry run)
- `/ai-mono-sync --commit` - Update pointers and commit changes
- `/ai-mono-sync --submodule backend` - Sync only one submodule

## 1. Verify Monorepo

```bash
if [ ! -f .gitmodules ]; then
    echo "ERROR: No .gitmodules found. This does not appear to be a monorepo."
    exit 1
fi
```

## 2. Resolve Tracked Branch Per Submodule

Each submodule tracks a specific branch configured in `.gitmodules`. IaC repos with a dev-to-main workflow should track `dev`; library repos track `main`.

```bash
tracked_branch_for() {
    local sub="$1"
    local branch
    branch=$(git config -f .gitmodules "submodule.${sub}.branch" 2>/dev/null)
    if [ -n "$branch" ]; then
        echo "$branch"
        return
    fi
    branch=$(cd "$sub" && git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')
    if [ -n "$branch" ]; then
        echo "$branch"
        return
    fi
    echo "main"
}
```

## 3. Fetch All Submodules

```bash
git submodule update --init --recursive
git submodule foreach git fetch --all --prune
```

## 4. Check Each Submodule

For each submodule, compare the current pointer with the tracked branch HEAD:

```bash
SUBMODULE="backend"
TRACKED=$(tracked_branch_for "$SUBMODULE")
POINTER_SHA=$(git submodule status "$SUBMODULE" | awk '{print $1}' | tr -d '+\-U')

cd "$SUBMODULE"
REMOTE_SHA=$(git rev-parse "origin/$TRACKED")

if [ "$POINTER_SHA" != "$REMOTE_SHA" ]; then
    BEHIND=$(git log --oneline "$POINTER_SHA..$REMOTE_SHA" | wc -l)
    NEW_COMMITS=$(git log --oneline "$POINTER_SHA..$REMOTE_SHA" --limit 5)
    echo "$SUBMODULE ($TRACKED): $BEHIND new commits"
    echo "$NEW_COMMITS"
fi
cd ..
```

## 5. Show Changes Before Acting

Display a summary of what would change:

```
Submodule pointer updates:
  backend  (tracks dev):   a1b2c3d -> x9y8z7w  (3 commits)
  frontend (tracks dev):   d4e5f6g -> d4e5f6g  (up to date)
  shared-lib (tracks main): h7i8j9k -> m3n4o5p  (1 commit)
```

If `--commit` was NOT passed, stop here and ask: "Apply these changes? Run `/ai-mono-sync --commit` to update and commit."

## 6. Update Pointers

```bash
# For each submodule that needs updating
TRACKED=$(tracked_branch_for "$SUBMODULE")
cd "$SUBMODULE"
git checkout "$TRACKED"
git pull origin "$TRACKED"
cd ..
```

## 7. Stage and Commit

```bash
# Stage submodule pointer changes
git add backend shared-lib  # only changed submodules

# Build commit message listing what changed
git commit -m "chore(deps): update submodule pointers

- backend (dev): a1b2c3d -> x9y8z7w (3 commits)
- shared-lib (main): h7i8j9k -> m3n4o5p (1 commit)"
```

## 8. Final Output

```
Submodule pointers updated and committed.

Updated:
  - backend (dev): 3 new commits
  - shared-lib (main): 1 new commit
Unchanged:
  - frontend (dev)

Commit: chore(deps): update submodule pointers
Next: git push or /ai-submit-work
```

## Error Handling
- **Not a monorepo**: Clear error
- **Submodule has local changes**: Warn and skip that submodule
- **Submodule in detached HEAD**: Re-attach to tracked branch before updating
- **No changes**: Exit cleanly with "All submodules are up to date"
- **No branch configured in .gitmodules**: Warn and fall back to remote HEAD or main
