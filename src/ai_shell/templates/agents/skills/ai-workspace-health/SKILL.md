---
name: ai-workspace-health
description: Analyze cross-repo workspace health, dependency order, and integration risks.
argument-hint: "[--repos name1,name2]"
---

Analyze workspace health: $ARGUMENTS

Use `augint-tools status --json $ARGUMENTS` when available and report:
- missing repos
- dirty repos blocking coordinated work
- branch drift against configured defaults
- dependency-order risks
- recommended cleanup steps
