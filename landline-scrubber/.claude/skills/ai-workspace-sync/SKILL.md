---
name: ai-workspace-sync
description: Synchronize all workspace repos, fetch latest, and report branch alignment across ai-lls-lib, ai-lls-api, ai-lls-web.
argument-hint: "[--fetch-only] [submodule-name]"
---

Synchronize all workspace repos and report cross-repo alignment: $ARGUMENTS

Ensures all three repositories are cloned, fetched, and reports branch alignment. Detects drift between repos and stale dependency references.

## 1. Validate Structure

```bash
cd "$(git rev-parse --show-toplevel)"
augint-tools status --json
```

If `augint-tools sync` is unavailable, explain that clone/fetch support is pending in
`augint-mono` and fall back to manual `git clone` / `git fetch`.

## 2. Fetch All Remotes

```bash
for repo in "${REPOS[@]}"; do
    echo "=== Fetching $repo ==="
    git -C "$repo" fetch --all --prune --tags 2>&1
done
```

If `--fetch-only` is in $ARGUMENTS, skip to Step 4 (Report).

## 3. Pull Updates

```bash
for repo in "${REPOS[@]}"; do
    BRANCH=$(git -C "$repo" branch --show-current)
    if [ -n "$BRANCH" ]; then
        echo "=== Pulling $repo ($BRANCH) ==="
        git -C "$repo" pull --no-rebase 2>&1
    else
        echo "=== $repo is in detached HEAD, skipping pull ==="
    fi
done
```

## 4. Check Dependency Alignment

```bash
augint-tools status --json
```

## 5. Report Status

```bash
augint-tools status
```

## 6. Suggest Actions

- If dependency drift detected: suggest `/ai-workspace-update`
- If branches misaligned: suggest `/ai-workspace-branch switch <branch>`
- If detached HEAD: suggest checking out a branch in the affected repo
- If all clean and aligned: report "System in sync"

## Error Handling
- **Repo not cloned**: Show clone command
- **Network failure on fetch**: Warn, continue with local data
- **Detached HEAD**: Show SHA, suggest checking out a branch
- **Merge conflicts on pull**: Stop, report conflict, suggest manual resolution
