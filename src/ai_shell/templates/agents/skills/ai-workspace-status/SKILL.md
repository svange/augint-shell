---
name: ai-workspace-status
description: Show cross-repo workspace status, open PRs, CI state, and next actions.
argument-hint: "[--repos name1,name2]"
---

Show workspace status: $ARGUMENTS

Run `uv run ai-tools mono status --json $ARGUMENTS`.

Report:
- repos that are missing, dirty, blocked, or behind target
- compact PR / CI rollup for repos needing action
- highest-priority next action

If this subcommand is unavailable, state that the installed `ai-tools` version is missing `mono status` and ask the user to upgrade `ai-tools`.
