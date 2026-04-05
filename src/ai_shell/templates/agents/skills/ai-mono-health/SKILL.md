---
name: ai-mono-health
description: Cross-repo health analysis covering dependency overlap, version alignment, and standards compliance. Use when asking 'check monorepo health' or 'cross-repo analysis'.
argument-hint: "[--submodule <name>]"
---

Analyze cross-repo health across all submodules: $ARGUMENTS

Checks dependency overlap, version alignment, submodule pointer freshness, and standards compliance across all submodules.

## Usage Examples
- `/ai-mono-health` - Full health analysis
- `/ai-mono-health --submodule backend` - Health check for one submodule

## 1. Verify Monorepo

```bash
if [ ! -f .gitmodules ]; then
    echo "ERROR: No .gitmodules found. This does not appear to be a monorepo."
    exit 1
fi
```

## 2. Resolve Tracked Branch Per Submodule

Each submodule tracks a specific branch configured in `.gitmodules`. IaC repos with a dev-to-main workflow should track `dev`; library repos track `main`.

```bash
tracked_branch_for() {
    local sub="$1"
    local branch
    branch=$(git config -f .gitmodules "submodule.${sub}.branch" 2>/dev/null)
    if [ -n "$branch" ]; then
        echo "$branch"
        return
    fi
    branch=$(cd "$sub" && git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')
    if [ -n "$branch" ]; then
        echo "$branch"
        return
    fi
    echo "main"
}
```

## 3. Submodule Pointer Freshness

For each submodule, check how far behind the pointer is from its tracked branch:

```bash
for SUBMODULE in $(git submodule status | awk '{print $2}'); do
    TRACKED=$(tracked_branch_for "$SUBMODULE")
    POINTER_SHA=$(git submodule status "$SUBMODULE" | awk '{print $1}' | tr -d '+\-U')
    cd "$SUBMODULE"
    git fetch --all --prune 2>/dev/null
    REMOTE_SHA=$(git rev-parse "origin/$TRACKED" 2>/dev/null)
    if [ "$POINTER_SHA" != "$REMOTE_SHA" ]; then
        BEHIND=$(git log --oneline "$POINTER_SHA..$REMOTE_SHA" | wc -l)
        DAYS=$(git log -1 --format="%cr" "$POINTER_SHA")
        echo "$SUBMODULE ($TRACKED): $BEHIND commits behind (pointer from $DAYS)"
    else
        echo "$SUBMODULE ($TRACKED): up to date"
    fi
    cd ..
done
```

## 4. Branch Configuration Audit

Check that each submodule has a tracked branch configured in `.gitmodules`:

```bash
for SUBMODULE in $(git submodule status | awk '{print $2}'); do
    BRANCH=$(git config -f .gitmodules "submodule.${SUBMODULE}.branch" 2>/dev/null)
    if [ -z "$BRANCH" ]; then
        echo "[WARN] $SUBMODULE: no branch set in .gitmodules (defaults to remote HEAD)"
        echo "  Fix: git config -f .gitmodules submodule.${SUBMODULE}.branch <branch>"
    else
        echo "[OK] $SUBMODULE: tracks $BRANCH"
    fi
done
```

## 5. Dependency Overlap Analysis

Scan each submodule for dependency files and find shared dependencies:

```bash
# Python repos: pyproject.toml, requirements.txt
# Node repos: package.json
# Terraform: versions.tf

for SUBMODULE in $(git submodule status | awk '{print $2}'); do
    if [ -f "$SUBMODULE/pyproject.toml" ]; then
        echo "[$SUBMODULE] Python project"
        # Extract dependencies
    elif [ -f "$SUBMODULE/package.json" ]; then
        echo "[$SUBMODULE] Node project"
        # Extract dependencies
    fi
done
```

Cross-reference shared dependencies and flag version mismatches:
- Same package at different versions across submodules
- Outdated versions relative to latest available

## 6. Standards Compliance

For each submodule, check:
- Pre-commit config exists and is consistent
- CI workflows follow standard patterns
- .editorconfig is present and consistent
- .gitignore covers standard patterns

```bash
for SUBMODULE in $(git submodule status | awk '{print $2}'); do
    echo "--- $SUBMODULE ---"
    [ -f "$SUBMODULE/.pre-commit-config.yaml" ] && echo "[OK] pre-commit" || echo "[MISSING] pre-commit"
    [ -f "$SUBMODULE/.editorconfig" ] && echo "[OK] editorconfig" || echo "[MISSING] editorconfig"
    [ -d "$SUBMODULE/.github/workflows" ] && echo "[OK] CI workflows" || echo "[MISSING] CI workflows"
done
```

## 7. Health Report

```
Monorepo Health Report
======================

Pointer Freshness:
  | Submodule  | Tracks | Status     | Behind | Last Updated |
  |------------|--------|------------|--------|--------------|
  | backend    | dev    | stale      | 5      | 3 days ago   |
  | frontend   | dev    | up to date | 0      | today        |
  | shared-lib | main   | up to date | 0      | today        |

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
  | requests  | 2.32.0  | -        | n/a      |

Standards Compliance:
  | Check       | backend | frontend | infra |
  |-------------|---------|----------|-------|
  | pre-commit  | OK      | OK       | MISS  |
  | editorconfig| OK      | OK       | OK    |
  | CI          | OK      | OK       | OK    |

Recommendations:
  1. Update stale pointers: /ai-mono-sync
  2. Set tracked branch for shared-lib: git config -f .gitmodules submodule.shared-lib.branch main
  3. Add pre-commit to infra: cd infra && /ai-standardize-precommit
```

## Error Handling
- **Not a monorepo**: Clear error
- **Submodule not initialized**: Suggest `/ai-mono-init`
- **No dependency files found**: Skip dependency analysis for that submodule
