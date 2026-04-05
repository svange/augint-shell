---
name: ai-mono-foreach
description: Run a command or skill in every submodule and aggregate results. Use when saying 'run across all repos' or 'in each submodule'.
argument-hint: "<command or skill>"
---

Run a command in every submodule: $ARGUMENTS

Iterates all submodules, runs the specified command or skill in each, and aggregates results.

## Usage Examples
- `/ai-mono-foreach git status` - Check git status in each submodule
- `/ai-mono-foreach uv sync` - Install deps in each Python submodule
- `/ai-mono-foreach /ai-standardize-repo --status` - Check standards in each submodule

## 1. Verify Monorepo

```bash
if [ ! -f .gitmodules ]; then
    echo "ERROR: No .gitmodules found. This does not appear to be a monorepo."
    exit 1
fi
```

## 2. Parse Arguments

The command to run is everything in `$ARGUMENTS`. It can be:
- A shell command: `git status`, `uv sync`, `npm install`
- A skill invocation: `/ai-standardize-repo --status`
- Any executable command

## 3. Iterate Submodules

```bash
SUBMODULES=$(git submodule status | awk '{print $2}')
TOTAL=$(echo "$SUBMODULES" | wc -l)
PASS=0
FAIL=0
SKIP=0

for SUBMODULE in $SUBMODULES; do
    echo ""
    echo "=== $SUBMODULE ==="

    if [ ! -d "$SUBMODULE" ]; then
        echo "SKIP: Directory not found (submodule not initialized)"
        SKIP=$((SKIP + 1))
        continue
    fi

    cd "$SUBMODULE"

    # Run the command
    # If it's a skill invocation (starts with /), handle accordingly
    # If it's a shell command, run it directly
    eval "$ARGUMENTS"
    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
        echo "PASS"
        PASS=$((PASS + 1))
    else
        echo "FAIL (exit code: $EXIT_CODE)"
        FAIL=$((FAIL + 1))
    fi

    cd ..
done
```

## 4. Aggregate Results

```
Foreach Results
===============

Command: git status
Submodules: 3 total

  | Submodule | Result |
  |-----------|--------|
  | backend   | PASS   |
  | frontend  | PASS   |
  | infra     | FAIL   |

Summary: 2 passed, 1 failed, 0 skipped
```

## 5. Handle Failures

If any submodule failed:
- List the failed submodules
- Suggest investigating: "Check failed submodule: `cd infra && <command>`"
- Do NOT stop on first failure -- always complete all submodules

## Error Handling
- **Not a monorepo**: Clear error
- **No arguments**: Ask what command to run
- **Submodule not initialized**: Skip with warning, count as skipped
- **Command not found**: Fail that submodule, continue to next
