---
name: ai-workspace-branch
description: Create or switch coordinated branches across selected workspace repos.
argument-hint: "<branch-name> [--repos name1,name2]"
---

Prepare coordinated branches: $ARGUMENTS

Run `uv run ai-tools mono branch --json $ARGUMENTS`.

Report created/switched branches and any repos blocked by local changes.
