---
name: ai-prepare-branch
description: Create a feature branch from the correct base (dev or main), sync release bumps, and set up remote tracking. Use when starting work on an issue or saying 'start working on'.
argument-hint: "[issue-number, description, or branch-name]"
---

Prepare a work branch with the configured repo policy: $ARGUMENTS

Primary command:
- `ai-tools repo branch prepare --json $ARGUMENTS`

Report:
- selected base branch and PR target branch
- prepared branch name
- repos/conditions blocked by local state
- next command to run
