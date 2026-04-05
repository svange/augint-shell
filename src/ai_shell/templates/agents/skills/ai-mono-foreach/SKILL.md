---
name: ai-mono-foreach
description: Run a command or skill in every submodule and aggregate results. Use when saying 'run across all repos' or 'in each submodule'.
argument-hint: "<command or skill>"
---

Run a command in every submodule: $ARGUMENTS

Iterates all submodules, runs the specified command or skill in each, and aggregates results.

**When to use foreach vs working in each submodule manually:**
- Use foreach for **read-only checks**: `git status`, test runs, dependency audits, standards checks
- Use **manual `cd` into each submodule** for development work: code changes, dependency updates, branch management, PR creation

## Usage Examples
- `/ai-mono-foreach git status` - Check git status in each submodule
- `/ai-mono-foreach uv sync` - Install deps in each Python submodule
- `/ai-mono-foreach /ai-standardize-repo --status` - Check standards in each submodule

## 1. Detect Command Type

Parse `$ARGUMENTS` to determine if it is:
- **Shell command** (does NOT start with `/`): delegate to CLI
- **Skill invocation** (starts with `/`): handle with AI iteration (step 3b)

## 2. Get Submodule List

If using the CLI path, the CLI handles submodule discovery. If using the AI path, list submodules:

```bash
ai-mono status --json | jq -r '.submodules[].name'
```

## 3a. Shell Command Path (CLI)

```bash
ai-mono foreach --json $ARGUMENTS
```

If `ai-mono` is not found, install it: `uv sync --all-extras`, then retry.

**JSON response:**
```json
{
  "command": "str",
  "results": [
    {"name": "str", "status": "PASS|FAIL|SKIP", "exit_code": 0, "stdout": "str", "stderr": "str"}
  ],
  "summary": {"passed": 0, "failed": 0, "skipped": 0}
}
```

To filter to a single submodule, pass `--submodule <name>` before `--`:
```bash
ai-mono foreach --json --submodule backend -- git status
```

## 3b. Skill Invocation Path (AI-Only)

The CLI cannot run AI skills. For skill invocations, iterate submodules manually:

For each submodule:
1. `cd` into the submodule directory
2. Invoke the skill (e.g., `/ai-standardize-repo --status`)
3. Record the result (pass/fail/output)
4. Return to monorepo root

Do NOT stop on first failure -- always complete all submodules.

## 4. Aggregate Results

Format results as a table:

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
- List the failed submodules with their stderr output
- Suggest investigating: "Check failed submodule: `cd infra && <command>`"
- For common failures, suggest specific fixes

## Error Handling
- **Not a monorepo**: CLI exits with error -- relay the message
- **No arguments**: Ask what command to run
- **Submodule not initialized**: CLI marks as SKIP -- note in output, suggest `/ai-mono-init`
- **Command not found**: CLI marks as FAIL with exit code 127 -- suggest checking the command
