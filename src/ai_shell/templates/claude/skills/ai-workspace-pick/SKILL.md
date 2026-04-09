---
name: ai-workspace-pick
description: Aggregate issues across workspace repos and recommend the best next task.
argument-hint: "[query or filters]"
---

Pick work across the workspace: $ARGUMENTS

Run `uv run ai-tools mono issues --json $ARGUMENTS`.

Return:
- 3 best issue candidates
- affected repos
- dependency order
- recommended branch plan
