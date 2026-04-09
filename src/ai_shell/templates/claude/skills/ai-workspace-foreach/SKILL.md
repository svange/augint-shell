---
name: ai-workspace-foreach
description: Run a command across selected child repos in a workspace.
argument-hint: "<command>"
---

Run the given command across workspace repos.

Run `uv run ai-tools mono foreach --json -- $ARGUMENTS`.

Summarize per repo:
- command executed
- pass/fail/skip
- actionable failures only
