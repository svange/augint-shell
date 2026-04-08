---
name: ai-workspace-init
description: Initialize a workspace repo for coordinated AI-driven development across child repos.
argument-hint: ""
---

Initialize this workspace.

Steps:
1. Run `/ai-init --workspace` if `ai-shell.toml` is missing.
2. Confirm workspace docs and manifest exist.
3. Use `augint-tools sync` to materialize child repos.
4. Use `/ai-workspace-status` to verify the workspace is ready.
