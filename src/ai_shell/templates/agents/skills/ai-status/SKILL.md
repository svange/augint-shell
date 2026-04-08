---
name: ai-status
description: Show current workspace status, open PRs, pipeline state, and suggested next step. Also triggered by 'where am I', 'what's going on', 'status'.
argument-hint: ""
---

Show current repo status and suggest the next action: $ARGUMENTS

Primary command:
- `ai-tools repo status --json $ARGUMENTS`

Summarize:
- branch and local git state (dirty / ahead / behind)
- open PR and latest CI state
- one recommended next action
