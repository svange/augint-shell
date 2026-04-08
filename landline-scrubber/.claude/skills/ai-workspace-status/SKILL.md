---
name: ai-workspace-status
description: High-level workspace dashboard showing all repo branches, open PRs, CI status, and dependency alignment across ai-lls-lib, api, web.
argument-hint: ""
---

Show high-level workspace dashboard with cross-repo status: $ARGUMENTS

Read-only overview of the entire Landline Scrubber workspace. Combines git status, GitHub PRs, CI pipeline state, and dependency version alignment across all three repos.

## 1. Run CLI Status

```bash
cd "$(git rev-parse --show-toplevel)"
augint-tools status --json
```

If `augint-tools status` is unavailable, explain that workspace support is pending in
`augint-mono` and fall back to direct `git`/`gh` inspection across the repo set.

## 2. Gather GitHub Data

For each repo, collect open PRs and latest CI runs:

```bash
REPOS=("ai-lls-lib" "ai-lls-api" "ai-lls-web")
GH_ORG="Augmenting-Integrations"

for repo in "${REPOS[@]}"; do
    echo "=== $repo ==="
    gh pr list --repo "$GH_ORG/$repo" --state open --limit 5 2>/dev/null || echo "  (gh unavailable)"
    echo "  dev CI:"
    gh run list --repo "$GH_ORG/$repo" --branch dev --limit 1 2>/dev/null || echo "  (gh unavailable)"
    echo "  main CI:"
    gh run list --repo "$GH_ORG/$repo" --branch main --limit 1 2>/dev/null || echo "  (gh unavailable)"
done
```

If `gh` commands fail, note "GitHub data unavailable (set GH_TOKEN to enable)" and show git-only info.

## 3. Branch Alignment Check

```bash
for repo in "${REPOS[@]}"; do
    BRANCH=$(git -C "$repo" branch --show-current 2>/dev/null || echo "DETACHED")
    echo "$repo: $BRANCH"
done
```

Report whether all repos are on the same branch type (all on dev, all on main, or mixed).

## 4. Suggest Next Action

Based on aggregate state, suggest ONE primary action:

| State | Suggestion |
|-------|-----------|
| All clean, aligned, CI passing | `/ai-pick-issue` |
| Dependency drift detected | `/ai-workspace-update` |
| Branch misalignment | `/ai-workspace-branch switch <branch>` |
| Uncommitted changes | `/ai-submit-work` (from dirty repo) |
| CI failing | `/ai-monitor-pipeline` (from failing repo) |
| Dev ahead of main, CI green | `/ai-promote` (from ready repo) |
| Repos behind upstream | `/ai-workspace-sync` |

## Error Handling
- **gh not authenticated**: Show git-only dashboard, note GitHub data unavailable
- **Repo not cloned**: Show as MISSING, suggest `augint-tools sync`
- **Detached HEAD**: Show commit SHA, flag as unusual
