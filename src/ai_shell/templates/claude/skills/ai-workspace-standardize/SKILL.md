---
name: ai-workspace-standardize
description: Standardize every child repo in a workspace.yaml-defined workspace by running /ai-standardize-repo --all on each child in dependency order, with consolidated baseline and post-run drift reporting via ai-tools workspace standardize --verify.
argument-hint: "[--verify] [--only name[,name...]] [--fail-fast|--continue-on-failure]"
---

Standardize every child repo in the workspace at `$ARGUMENTS`.

This is the workspace-level entry point for repository standardization.
It orchestrates the single-repo `/ai-standardize-repo --all` skill across
every child repo defined in a `workspace.yaml` file, in dependency order,
and produces a consolidated drift report before and after. It is
prose-only -- no new Python module -- and defers the heavy lifting to
`ai-tools` (for workspace enumeration and bulk verify) and
`/ai-standardize-repo` (for each child's 10-step sequence).

## Constraints (read these first)

- **Workspace root only.** Run this skill from a directory containing
  `workspace.yaml`. Never from inside a child repo. If you detect that
  the current directory is a subdirectory of a workspace (`workspace.yaml`
  in a parent), tell the user to `cd` up and stop.
- **Never `cd` into a child directory** to run `uv run` or any other
  command. Always pass the child path as an argument. Why: the workspace
  shares a single venv at `/root/.cache/uv/venvs/project/`. When you
  `cd` into a child and run `uv run`, uv re-solves dependencies against
  the child's `pyproject.toml` floor (e.g. `augint-shell>=0.42.0`) and
  downgrades the shared venv to that floor. The next child you touch then
  has a stale install. This trap was hit during the Phase 2 dry-run and
  is the reason all commands in this skill must use `<child-path>` args.
- **Use `workspace.yaml` for enumeration, not `.ai-shell.toml`.**
  `.ai-shell.toml` is scoped to AI agent configuration (container
  settings, model provider); it is not a workspace descriptor. Read
  workspace structure through `ai-tools workspace inspect` (which uses
  `augint_tools.config.workspace.load_workspace_config()` under the
  hood), never by direct parsing of `.ai-shell.toml`.
- **Prose-driven, not Python-driven.** This skill owns the orchestration
  loop. Python provides the building blocks (`ai-tools workspace
  inspect`, `ai-tools workspace standardize --verify`,
  `/ai-standardize-repo --all`) but the loop itself is Claude reading
  the inspect output, iterating, and capturing results.

## Process

### Step 1 -- detect workspace mode

Run:

```bash
uv run ai-tools --json workspace inspect
```

Parse `result.repos` from the JSON output. Each entry has at minimum
`name`, `path`, `repo_type`, `base_branch`, `depends_on`, and where
`ai-tools` provides them, `language` and `framework`.

If the command fails with a message like "No workspace.yaml found",
emit:

> This skill only runs in a workspace repository. A `workspace.yaml`
> file must be present at the workspace root. If you are inside a child
> repo, `cd` up until you see `workspace.yaml` in the directory listing.
> If you need to create a new workspace, file a ticket for a
> workspace-init skill -- that is tracked separately.

and stop.

### Step 2 -- parse arguments

`$ARGUMENTS` may contain:

- `--verify` -- read-only mode. Only run Step 4 (bulk baseline verify)
  and exit after printing the report. Do NOT run per-child standardize.
- `--only <name>[,<name>...]` -- restrict the run to the listed
  children. Names must match `repos[].name` from `workspace.yaml`. If
  any name is unknown, abort with a clear error listing the valid
  options.
- `--fail-fast` (default) -- stop at the first child that fails.
- `--continue-on-failure` -- log per-child failures, keep going, report
  aggregated failures at the end.

### Step 3 -- determine execution order

Derive order from `depends_on` across children:

1. Build a directed graph: child -> [children it depends on]
2. Topologically sort so children with no dependencies run first
3. If the sort fails (cycle detected), emit a clear error including the
   cycle path (e.g. `a -> b -> c -> a`) and stop
4. If `ai-tools workspace graph --json` becomes implemented upstream,
   prefer its output over the in-skill topo sort

For the reference landline-scrubber workspace the expected order is
`ai-lls-lib -> ai-lls-api -> ai-lls-web` (`ai-lls-lib` has no deps;
`ai-lls-api` depends on it; `ai-lls-web` depends on `ai-lls-api`).

Filter the ordered list by any `--only` argument.

### Step 4 -- baseline bulk verify

Run:

```bash
uv run ai-tools --json workspace standardize --verify
```

(append `--only <names>` if the user passed `--only`).

Parse the aggregated drift report. Present it as a compact table. For
the landline-scrubber example, the table looks like:

```
Workspace: landline-scrubber
Order: ai-lls-lib -> ai-lls-api -> ai-lls-web

  Repo          | Type            | Lang     | Status | Drift sections
  --------------+-----------------+----------+--------+---------------------------------------
  ai-lls-lib    | python/library  | python   | DRIFT  | pipeline, precommit, renovate, rulesets, repo_settings
  ai-lls-api    | python/service  | python   | DRIFT  | pipeline, precommit, renovate, rulesets, repo_settings
  ai-lls-web    | node/service    | node     | DRIFT  | pipeline, precommit, renovate, rulesets, repo_settings

Aggregate: 3 repos checked, 0 clean, 3 drift, 0 fail, 0 error
```

If the user passed `--verify`, stop here and exit: code 0 if every repo
is `clean`, 1 if any has drift, 2 if any errored.

**Fallback when `ai-tools workspace standardize --verify` is not
available.** If the command exits non-zero with a message like "unknown
command" or "No such option", fall back to per-child calls:

```bash
uv run ai-shell standardize repo --verify <child-path>
```

for each child in order, aggregating the output in prose. Emit a warning:

> `ai-tools workspace standardize --verify` is not installed. Running
> per-child verify as a fallback -- this is slower and produces more
> context. Upgrade `ai-tools` to the version that ships T6-1 for the
> efficient path.

### Step 5 -- per-child standardize (write phase)

This step only runs when `--verify` was NOT passed.

For each child in the determined order, print a banner:

```
[1/3] ai-lls-lib (python/library, ./ai-lls-lib)
```

Then **invoke `/ai-standardize-repo --all <path>` as a sub-skill.** The
sub-skill runs the full 10-step sequence for that child:

1. Detect language x type
2. Dotfiles
3. Pre-commit
4. Pipeline -- AI-mediated merge (T5-7)
5. Renovate
6. Release
7. OIDC
8. Repo settings
9. Rulesets
10. Verify

The sub-skill handles its own `AskUserQuestion` prompts (detection
ambiguity, multi-candidate rulesets, parallel post-deploy test pattern
disambiguation) and reports its own `PASS` / `DRIFT` / `FAIL` summary.
Capture that summary into the workspace report.

Reminder: pass `<child-path>` as an argument. Do not `cd` into the child.

After the sub-skill returns:

- If it succeeded, record the child as `PASS` in the workspace report
  and move to the next child.
- If it failed:
  - `--fail-fast` (default): stop. Print a consolidated partial report
    showing which children succeeded before the failure. Exit non-zero
    with a pointer to the failing child and its drift report.
  - `--continue-on-failure`: log the failure in the workspace report,
    continue with the next child.

### Step 6 -- post-run bulk verify

After all children are processed (or fail-fast triggered), re-run the
bulk verify:

```bash
uv run ai-tools --json workspace standardize --verify
```

This is the authoritative clean-state check. Present the same table
format as Step 4. If every repo is now clean, emit the success banner:

```
Workspace landline-scrubber: all 3 repos standardized
  ai-lls-lib (python/library)    PASS
  ai-lls-api (python/service)    PASS
  ai-lls-web (node/service)      PASS
```

If any drift remains, report it with a clear next action (most likely:
re-run the skill, or investigate a specific child -- `/ai-standardize-repo --verify <path>`).

### Step 7 -- consolidated workspace report

Aggregate across all children and present:

- **Baseline drift section counts** from Step 4 (how much work was
  queued at the start)
- **Per-child result summary** from Step 5 (PASS / DRIFT / FAIL)
- **Final drift state** from Step 6
- **Any AskUserQuestion answers** the sub-skills captured -- especially
  disambiguation calls for parallel post-deploy test patterns, since
  those are useful for the friction log
- **Total elapsed time** per child and overall
- **Next actions**:
  - If clean: "Workspace is standardized. Push PRs per child, or use
    `/ai-workspace-submit` for coordinated submission."
  - If drift remains: point at the specific children + sections that
    still need attention.

Append the workspace report to `PHASE_2_FRICTION_LOG.md` at the
workspace root as a dated entry. Create the file if it does not exist.

## Reporting

At the end of every run, regardless of success or failure, print:

- The execution order that was used
- The list of children processed and their final state
- Any sub-skill failures with the child name and a one-line reason
- The path to the friction log entry that was appended

Keep the report compact. The user's friction log is the durable record;
the in-terminal output is a quick-scan summary.
