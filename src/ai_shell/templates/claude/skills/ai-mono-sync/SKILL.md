---
name: ai-mono-sync
description: Sync submodule pointers to latest tracked branch HEAD. Use when saying 'update submodules', 'sync repos', or 'update pointers'.
argument-hint: "[--commit] [--submodule <name>]"
---

Sync submodule pointers to their latest tracked branch HEAD: $ARGUMENTS

Updates submodule pointers to the latest commit on each submodule's tracked branch (configured in `.gitmodules`), optionally staging and committing the pointer changes.

Sync after PRs are merged in a submodule, not while feature branches are in progress. Syncing picks up whatever is on the tracked branch (typically `dev` or `main`).

## Usage Examples
- `/ai-mono-sync` - Show what would change (dry run)
- `/ai-mono-sync --commit` - Update pointers and commit changes
- `/ai-mono-sync --submodule backend` - Sync only one submodule

## 1. Preview Changes

```bash
ai-mono sync --json $ARGUMENTS
```

If `ai-mono` is not found, install it: `uv sync --all-extras`, then retry.

If `--commit` was passed in $ARGUMENTS, skip to step 3.

**JSON response:**
```json
{
  "submodules": [
    {
      "name": "str",
      "tracked_branch": "str",
      "pointer_sha": "full SHA",
      "remote_sha": "full SHA or null",
      "behind": 0,
      "updated": false
    }
  ],
  "committed": false,
  "commit_sha": null
}
```

## 2. Show Changes and Ask for Confirmation

Display what would change:

```
Submodule pointer updates:
  backend  (tracks dev):    a1b2c3d -> x9y8z7w  (3 commits)
  frontend (tracks dev):    d4e5f6g -> d4e5f6g  (up to date)
  shared-lib (tracks main): h7i8j9k -> m3n4o5p  (1 commit)
```

If any submodule is >20 commits behind, warn: "backend is 47 commits behind -- consider reviewing changes before syncing."

If no submodules need updating: "All submodules are up to date. No action needed." Stop here.

Otherwise, ask: "Apply these changes? Run `/ai-mono-sync --commit` to update and commit."

## 3. Apply Changes

When `--commit` is in $ARGUMENTS (or user confirms):

```bash
ai-mono sync --commit --json [--submodule "$NAME"]
```

The CLI handles: fetching, updating pointers, staging, and committing with a `chore(deps): update submodule pointers` message listing each updated submodule.

## 4. Report Results

Parse the JSON response. If `committed` is true:

```
Submodule pointers updated and committed.

Updated:
  - backend (dev): 3 new commits
  - shared-lib (main): 1 new commit
Unchanged:
  - frontend (dev)

Commit: <commit_sha>
Next: git push or /ai-submit-work
```

If `committed` is false but updates were expected, warn that something went wrong.

## Error Handling
- **Not a monorepo**: CLI exits with error -- relay the message
- **Submodule has local changes**: CLI may fail to update -- warn and suggest stashing
- **No changes**: Exit cleanly with "All submodules are up to date"
- **Specified submodule not found**: CLI exits with error -- relay and list available submodules
