---
name: ai-workspace-lint
description: Run manifest-defined quality checks across selected workspace repos.
argument-hint: "[--repos name1,name2] [--fix]"
---

Run workspace quality checks: $ARGUMENTS

Run `ai-tools mono check --phase quality --json $ARGUMENTS`.

Summarize fixes applied and any remaining failures.
