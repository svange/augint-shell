---
name: ai-workspace-sync
description: Clone missing child repos and fetch/update existing repos for a workspace.
argument-hint: "[--repos name1,name2] [--dry-run]"
---

Sync the workspace repos: $ARGUMENTS

Run `uv run ai-tools workspace sync --json $ARGUMENTS`.

Summarize:
- cloned repos
- updated repos
- repos with local changes that blocked updates
- next recommended command
