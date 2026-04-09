---
name: ai-workspace-update
description: Update downstream repos after upstream merges or releases in a workspace.
argument-hint: "[--from repo-name]"
---

Update downstream workspace dependencies: $ARGUMENTS

Run `uv run ai-tools mono update --json $ARGUMENTS`.

Summarize changed repos and any follow-up release or validation steps.
