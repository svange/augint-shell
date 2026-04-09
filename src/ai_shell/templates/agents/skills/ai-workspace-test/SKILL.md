---
name: ai-workspace-test
description: Run manifest-defined tests across selected workspace repos in dependency order.
argument-hint: "[--repos name1,name2]"
---

Run workspace tests: $ARGUMENTS

Run `uv run ai-tools mono check --phase tests --json $ARGUMENTS`.

Summarize failing repos first, then the overall pass/fail state.
