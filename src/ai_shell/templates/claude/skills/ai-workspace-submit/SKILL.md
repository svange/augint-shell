---
name: ai-workspace-submit
description: Push coordinated branches and open PRs for the affected workspace repos.
argument-hint: "[--repos name1,name2] [--dry-run]"
---

Submit coordinated workspace changes: $ARGUMENTS

Use `augint-tools submit $ARGUMENTS`.

Report:
- pushed repos
- PR targets used
- PR links if available
- blockers requiring manual intervention
