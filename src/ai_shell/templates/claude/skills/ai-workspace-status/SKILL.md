---
name: ai-workspace-status
description: Show cross-repo workspace status, open PRs, CI state, and next actions.
argument-hint: "[--repos name1,name2]"
---

Show workspace status: $ARGUMENTS

Use `augint-tools status $ARGUMENTS`.

Report:
- repo presence and sync state
- branch / dirty / ahead-behind state per repo
- open PR / CI summary when available
- highest-priority next action

If `augint-tools` is missing, say so and tell the user to install it.
