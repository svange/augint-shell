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

## 1. Get Status Data

```bash
ai-mono status --json $ARGUMENTS
```

If `ai-mono` is not found, install it: `uv sync --all-extras`, then retry.

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
      "open_prs": 0,
      "ci_status": "passing|failing|unknown"
    }
  ],
  "summary": {"total": 0, "stale": 0, "up_to_date": 0},
  "recommendations": ["str"]
}
```

## 2. Format Dashboard

Present results as a table:

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

Use the first 7 characters of pointer_sha for display.

## 3. AI Analysis

Go beyond the CLI's raw data:

- **Priority ordering**: Which submodule needs attention most urgently? Failing CI > stale pointers > open PRs needing review.
- **Cross-referencing**: Do any open PRs correspond to stale pointers? (e.g., a merged PR in a submodule that hasn't been synced yet)
- **Blocked work detection**: Are stale pointers blocking other submodules' work?

## 4. Suggested Next Actions

Based on status, suggest specific actions:
- If submodules are behind: "Run `/ai-mono-sync` to update pointers"
- If CI is failing: "Check frontend: `cd frontend && /ai-monitor-pipeline`"
- If PRs need review: List them with links
- If everything is clean: "All submodules are up to date. No action needed."

Include the CLI's `recommendations` array but enhance with skill-specific suggestions.

## Error Handling
- **Not a monorepo**: CLI exits with error -- relay the message
- **Submodule not initialized**: Suggest `/ai-mono-init`
- **No GitHub remote / gh CLI missing**: CLI warns and returns `open_prs: 0`, `ci_status: "unknown"` -- note this in output
