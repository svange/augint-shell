---
name: ai-mono-health
description: Cross-repo health analysis covering dependency overlap, version alignment, and standards compliance. Use when asking 'check monorepo health' or 'cross-repo analysis'.
argument-hint: "[--submodule <name>]"
---

Analyze cross-repo health across all submodules: $ARGUMENTS

Checks submodule pointer freshness, branch configuration, standards compliance, and dependency overlap across all submodules.

## Usage Examples
- `/ai-mono-health` - Full health analysis
- `/ai-mono-health --submodule backend` - Health check for one submodule

## 1. Get Health Data

```bash
ai-mono health --json $ARGUMENTS
```

If `ai-mono` is not found, install it: `uv sync --all-extras`, then retry.

**JSON response:**
```json
{
  "freshness": [
    {"name": "str", "tracked_branch": "str", "behind": 0, "status": "up_to_date|stale"}
  ],
  "branch_config": [
    {"name": "str", "configured_branch": "str or null", "status": "ok|missing"}
  ],
  "standards": [
    {"name": "str", "pre_commit": true, "editorconfig": true, "ci_workflows": true}
  ],
  "recommendations": ["str"]
}
```

## 2. Dependency Overlap Analysis (AI-Only)

This analysis is NOT in the CLI -- perform it directly by reading dependency files in each submodule.

For each submodule, scan for dependency files:
- **Python**: `pyproject.toml` (under `[project.dependencies]` and `[dependency-groups]`), `requirements.txt`
- **Node**: `package.json` (under `dependencies` and `devDependencies`)
- **Terraform**: `versions.tf` (provider version constraints)

Cross-reference shared dependencies across submodules:
- Same package at different versions
- Outdated versions relative to other submodules
- Conflicting version constraints

## 3. Build Health Report

Combine CLI data with the dependency analysis:

```
Monorepo Health Report
======================

Pointer Freshness:
  | Submodule  | Tracks | Status     | Behind |
  |------------|--------|------------|--------|
  | backend    | dev    | stale      | 5      |
  | frontend   | dev    | up to date | 0      |
  | shared-lib | main   | up to date | 0      |

Branch Config:
  | Submodule  | .gitmodules branch | Status |
  |------------|--------------------|--------|
  | backend    | dev                | OK     |
  | frontend   | dev                | OK     |
  | shared-lib | (not set)          | WARN   |

Dependency Overlap:
  | Package   | backend | frontend | Aligned? |
  |-----------|---------|----------|----------|
  | pydantic  | 2.9.0   | -        | n/a      |
  | boto3     | 1.35.0  | 1.34.0   | NO       |

Standards Compliance:
  | Check       | backend | frontend | infra |
  |-------------|---------|----------|-------|
  | pre-commit  | OK      | OK       | MISS  |
  | editorconfig| OK      | OK       | OK    |
  | CI          | OK      | OK       | OK    |
```

## 4. Prioritized Recommendations

Merge CLI `recommendations` with dependency analysis findings. Order by urgency:

1. **Failing standards** (missing pre-commit, CI): suggest specific skills (e.g., "Add pre-commit to infra: `cd infra && /ai-standardize-precommit`")
2. **Stale pointers**: suggest `/ai-mono-sync`
3. **Missing branch config**: suggest `git config -f .gitmodules submodule.<name>.branch <branch>`
4. **Dependency mismatches**: flag which packages are out of alignment and suggest updating

## Error Handling
- **Not a monorepo**: CLI exits with error -- relay the message
- **Submodule not initialized**: Suggest `/ai-mono-init`
- **No dependency files found**: Skip dependency analysis for that submodule, note in output
