---
name: ai-workspace-branch
description: Create or switch feature branches across multiple repos for cross-cutting changes. Ensures consistent branch naming.
argument-hint: "[issue-number or branch-name] [--repos lib,api,web | --all]"
---

Create or switch branches across workspace repos for cross-cutting changes: $ARGUMENTS

Handles the common case of cross-cutting changes that touch multiple repos. Creates identically-named branches in each repo from their respective base branches.

## 1. Parse Arguments

From $ARGUMENTS, determine:
- **Branch input**: issue number, branch name, or description text
- **Target repos**: `--repos lib,api,web` or `--all` or auto-detect
- **Mode**: `switch` (existing branch) or create (new branch)

Repo shorthand: `lib` = ai-lls-lib, `api` = ai-lls-api, `web` = ai-lls-web.

## 2. Auto-Detect Repos (if not specified)

If `--repos` and `--all` not provided, infer from context:
- Keywords like "lib", "library", "core", "verifier", "processor" -> lib + api
- Keywords like "handler", "lambda", "endpoint", "api" -> api only
- Keywords like "frontend", "web", "vue", "ui", "component" -> web only
- Ambiguous -> ask user which repos

## 3. Check for Uncommitted Work

For each target repo:
```bash
cd "$MONO_ROOT/$repo"
STATUS=$(git status --porcelain)
UNPUSHED=$(git rev-list --count @{upstream}..HEAD 2>/dev/null || echo "0")
```

If dirty or unpushed: **warn and ask** (stash / skip / abort). Never silently discard work.

## 4. Determine Branch Name

Use the same conventions as `/ai-prepare-branch`:
- Numeric input -> fetch issue from GitHub, generate `{type}/issue-{N}-{slug}`
- Already contains `/` -> use as-is
- Description text -> auto-detect type prefix, generate slug

Branch name format: `{type}/issue-{N}-{slug}` where type is feat, fix, docs, refactor, test, chore, ci, build, style, revert, perf.

## 5. Create or Switch Branches

```bash
augint-tools branch $ARGUMENTS
```

If `augint-tools branch` is unavailable, explain that coordinated branch creation is
pending in `augint-mono` and fall back to per-repo branch setup.

## 6. Report

```
Branch: feat/issue-42-new-export
Repos:
  ai-lls-lib   Base: dev   Tracking: origin/feat/issue-42-new-export
  ai-lls-api   Base: dev   Tracking: origin/feat/issue-42-new-export

Suggested workflow:
  1. Make changes in ai-lls-lib first (upstream dependency)
  2. Test: /ai-workspace-test
  3. Submit each repo: /ai-workspace-submit
```

## Error Handling
- **Branch exists in some repos but not others**: Offer to create in remaining repos
- **Uncommitted work**: Never silently discard
- **Issue not found in any repo**: Suggest using a branch name directly
- **Push fails**: Branch created locally, warn about push failure
