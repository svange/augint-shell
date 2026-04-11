---
name: ai-workspace-init
description: Initialize a workspace repo for coordinated AI-driven development across child repos.
argument-hint: ""
---

Initialize this workspace.

Steps:
1. Run `/ai-init --workspace` if `ai-shell.toml` is missing.
2. Confirm workspace docs and manifest exist.
3. Run `uv run ai-tools workspace sync --json` to materialize child repos.
4. Run `uv run ai-tools workspace inspect --json` to verify dependency graph, selectors, and branch targets.
5. If `workspace inspect` is unavailable, run `uv run ai-tools workspace status --json` and report blockers.
