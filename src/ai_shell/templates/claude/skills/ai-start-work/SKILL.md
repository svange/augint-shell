---
name: ai-start-work
description: Pick an issue, discuss approach, sync branches, and create a feature branch in one flow. Use when starting new work on an issue.
argument-hint: "[issue-number or search-terms]"
---

Start a new unit of work end-to-end: find an issue, align on approach, sync branches, and create a feature branch: $ARGUMENTS

Combines the full workflows of ai-pick-issue and ai-prepare-branch into a single uninterruptible flow so that branch preparation (including dev-from-main sync) never gets skipped.

## Usage Examples
- `/ai-start-work 42` - Start work on issue #42
- `/ai-start-work auth bug` - Find and start work on an auth-related issue
- `/ai-start-work` - Get recommendations, pick one, and start

---

# Phase 1: Find the Issue

## 1. Parse Input Type

```bash
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "Error: Not in a git repository"
    exit 1
fi

REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)
if [ -z "$REPO" ]; then
    echo "Error: Could not determine repository. Make sure 'gh' is authenticated."
    exit 1
fi
```

Analyze $ARGUMENTS:
- **Numeric only** (e.g., "42", "123") -> Direct issue lookup
- **Keywords** (e.g., "auth", "devops") -> Keyword search
- **Natural language** (e.g., "the one about...") -> Smart search
- **Empty** -> Issue recommendation mode

## 2. Direct Issue Lookup (Numeric)

```bash
gh issue view $ISSUE_NUMBER --json number,title,state,labels,assignees,body,comments
```

- Show title, state, labels, assignee
- Display description and recent comments
- **IMPORTANT**: If state is "CLOSED", warn user prominently

## 3. Search Mode (Keywords/Natural Language)

```bash
gh issue list --state open --search "$ARGUMENTS" --limit 30 --json number,title,labels,updatedAt,comments
```

For natural language queries: extract key terms, remove filler words, search in title and body.

## 4. Recommendation Mode (Empty Arguments)

When no arguments provided, recommend OPEN issues only:

```bash
gh issue list --state open --limit 100 --json number,title,labels,createdAt,updatedAt,comments,assignees,body
```

Score and rank by: priority labels, age, activity, assignment status, implementation readiness.

Present as a ranked table and recommend the top candidate.

**IMPORTANT**: Only recommend or list OPEN issues. If user specifies a closed issue, show it but warn prominently.

---

# Phase 2: Design Conversation

## 5. Collaborative Design Dialogue

After presenting the issue, engage the user in a focused design dialogue:

1. **Summarize your understanding** of the issue in 2-3 sentences
2. **Propose an implementation approach** - identify key files, components, or architecture
3. **Surface trade-offs and open questions** - flag ambiguities, alternatives, or constraints
4. **Ask 2-4 specific clarifying questions** about requirements, scope, architecture, or constraints

### Continue the Dialogue

- Listen to answers, refine understanding
- Propose a more detailed plan when you have enough context
- Ask follow-ups if answers reveal new ambiguities
- Challenge assumptions respectfully

### Confirm Alignment

When alignment is reached, present:

```
=== Proposed Approach ===
Goal: [one sentence]
Approach: [2-3 key decisions]
Files likely affected: [list]
Out of scope: [what we're NOT doing]
```

Then ask: **"Does this match your intent? Ready to create the branch?"**

**Only proceed to Phase 3 after explicit user confirmation.**

---

# Phase 3: Prepare the Branch

## 6. Detect Repo Branching Pattern

```bash
git fetch --all --prune

DEV_BRANCH=""
for candidate in dev develop staging; do
    if git show-ref --verify --quiet refs/remotes/origin/$candidate; then
        DEV_BRANCH=$candidate
        break
    fi
done

DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@' 2>/dev/null || echo "main")
```

Set base branch:
- Dev-based repos: base = `$DEV_BRANCH`
- Main-only repos: base = `$DEFAULT_BRANCH`

Report: "Repo pattern: [dev-based|main-only]. Base branch: [branch]. PR target: [branch]."

## 7. Check Current State

```bash
CURRENT_BRANCH=$(git branch --show-current)
```

Three-state check:
1. **On main/dev** - proceed normally
2. **On a work branch with no changes** - offer to switch
3. **On a work branch with uncommitted changes OR unpushed commits** - dangerous:
   - Show status: X uncommitted files, Y unpushed commits
   - Check for open PR: `gh pr list --head $CURRENT_BRANCH --state open`
   - Offer: (a) stash and switch, (b) submit current work first, (c) abort

**Never silently discard work.**

## 8. Sync Release Bumps (Dev-based Repos Only)

```bash
if ! git merge-base --is-ancestor origin/$DEFAULT_BRANCH origin/$DEV_BRANCH; then
    echo "dev is behind main. Syncing release bump commits..."

    MAIN_RUN_STATUS=$(gh run list --branch $DEFAULT_BRANCH --limit 1 --json status -q '.[0].status' 2>/dev/null)
    if [ "$MAIN_RUN_STATUS" = "in_progress" ] || [ "$MAIN_RUN_STATUS" = "queued" ]; then
        echo "WARNING: A CI/release pipeline is running on main."
        echo "Wait for it to complete before branching, or you may need to rebase later."
        # Ask user: wait / continue anyway / abort
    fi

    git checkout $DEV_BRANCH
    git merge origin/$DEFAULT_BRANCH
    # If merge succeeds: push
    # If conflicts: abort merge, tell user to resolve manually
fi
```

On conflict: `git merge --abort` and tell user to create a `chore/sync-dev-with-main` branch.

## 9. Update Base Branch

```bash
BASE=$DEV_BRANCH  # or $DEFAULT_BRANCH for main-only repos
git checkout $BASE
git pull origin $BASE
```

## 10. Create Branch

### From issue number:
```bash
gh issue view $ISSUE_NUMBER --json title,labels
# Detect type from labels: bug -> fix/, feature/enhancement -> feat/, docs -> docs/
# Default -> feat/
SLUG=$(echo "$TITLE" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | sed 's/[^a-z0-9-]//g' | cut -c1-40)
BRANCH_NAME="$PREFIX/issue-$ISSUE_NUMBER-$SLUG"
```

### From description (non-issue mode):
Auto-detect type prefix from keywords (fix, docs, test, refactor, chore, perf, feat).

### Handle existing branch:
```bash
if git show-ref --verify --quiet refs/heads/$BRANCH_NAME; then
    echo "Branch $BRANCH_NAME already exists."
    # Suggest: $BRANCH_NAME-2 or ask for alternative
fi
```

## 11. Create and Push

```bash
git checkout -b $BRANCH_NAME
git push -u origin $BRANCH_NAME
```

## 12. Final Output

```
=== Ready to Work ===
Issue: #42 - Fix authentication timeout
Branch: fix/issue-42-fix-auth-timeout
Base: dev
PR target: dev
Remote tracking: origin/fix/issue-42-fix-auth-timeout
Sync: dev is up to date with main

Approach:
  [brief summary from design conversation]

Next steps:
  - Make your changes
  - When ready: /ai-submit-work
```

## Error Handling
- **Issue not found**: Suggest checking number or searching
- **Closed issue**: Warn prominently, ask if user wants to proceed anyway
- **Rebase/merge in progress**: Warn and suggest completing or aborting first
- **Uncommitted changes**: Offer stash/submit/abort (never discard)
- **Release pipeline in flight**: Warn about potential stale base
- **Branch exists**: Suggest alternative name
- **Sync conflict**: Abort merge, suggest dedicated resolution branch
