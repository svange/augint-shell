---
name: ai-workspace-standardize
description: Standardize every child repo in a workspace.yaml-defined workspace by looping over children in dependency order and calling `ai-tools standardize <child-path> --verify --json` (baseline), `--all` (apply), then `--verify --json` again (post-apply). Aggregates results into a consolidated workspace report.
argument-hint: "[--verify] [--only name[,name...]] [--fail-fast|--continue-on-failure]"
---

Standardize every child repo in the workspace at `$ARGUMENTS`.

This is the workspace-level entry point for repository standardization.
It loops over every child repo defined in `workspace.yaml`, in
dependency order, and runs `ai-tools standardize <child-path>` three
times per child: a baseline `--verify --json`, an `--all` write phase,
and a post-apply `--verify --json`. Results are aggregated into a
consolidated drift report.

## Constraints (read these first)

- **Workspace root only.** Run this skill from a directory containing
  `workspace.yaml`. Never from inside a child repo. If you detect that
  the current directory is a subdirectory of a workspace (`workspace.yaml`
  in a parent), tell the user to `cd` up and stop.
- **All `ai-tools standardize` calls pass the child path as an argument
  and are run from the workspace root.** Do not `cd` into a child repo.
  `uv run` inside a child re-solves the child's lockfile and can
  downgrade augint-tools in the shared workspace venv.
- **Use `workspace.yaml` for enumeration, not `.ai-shell.toml`.**
  `.ai-shell.toml` is scoped to AI agent configuration (container
  settings, model provider); it is not a workspace descriptor. Read
  workspace structure through `ai-tools workspace inspect` (which uses
  `augint_tools.config.workspace.load_workspace_config()` under the
  hood), never by direct parsing of `.ai-shell.toml`.
- **Prose-driven, not Python-driven.** This skill owns the
  orchestration loop. Python provides the building blocks
  (`ai-tools workspace inspect` for enumeration,
  `ai-tools standardize <path> --verify --json` for drift,
  `ai-tools standardize <path> --all` for write) but the loop itself is
  Claude reading the inspect output, iterating child by child, and
  aggregating results.

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

- `--verify` -- read-only mode. Only run Step 4 (per-child baseline
  verify) and exit after printing the report. Do NOT run the write
  phase.
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

### Step 4 -- baseline per-child verify

For each child in execution order, run:

```bash
uv run ai-tools standardize <child-path> --verify --json
```

Capture each child's JSON output. Exit codes:
- `0` -- clean, no drift
- `1` -- drift present (check the `findings` array for affected sections)
- any other non-zero -- error; record and continue per
  `--fail-fast` / `--continue-on-failure`

Aggregate into a compact table:

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
is clean, 1 if any has drift, 2 if any errored.

### Step 5 -- per-child standardize (write phase)

This step only runs when `--verify` was NOT passed.

For each child in execution order, print a banner:

```
[1/3] ai-lls-lib (python/library, ./ai-lls-lib)
```

Then run:

```bash
uv run ai-tools standardize <child-path> --all
```

Capture stdout / stderr / exit code. The underlying umbrella runs the
10-step sequence for the child:

1. Detect language x type
2. Dotfiles
3. Pre-commit
4. Pipeline (may return `NEEDS_ACTION` -- see below)
5. Renovate
6. Release
7. OIDC (returns `NEEDS_ACTION` -- the Python umbrella does not touch
   AWS IAM)
8. Repo settings (`ai-gh config --standardize`)
9. Rulesets (`ai-gh rulesets apply <spec>`)
10. Verify

**`NEEDS_ACTION` is not a failure.** If the umbrella reports
`NEEDS_ACTION` for pipeline or OIDC, that means an AI-mediated sub-step
(`/ai-standardize-pipeline` or `/ai-setup-oidc`) should be invoked
separately per child to complete the sequence. Record this in the
workspace report as a follow-up action; do not treat it as a child
failure.

After the call returns:

- **Exit 0** -- record the child as `PASS` in the workspace report and
  move to the next child.
- **Exit non-zero** --
  - `--fail-fast` (default): stop. Print a consolidated partial report
    showing which children succeeded before the failure. Exit non-zero
    with a pointer to the failing child and its drift report.
  - `--continue-on-failure`: log the failure in the workspace report,
    continue with the next child.

Reminder: pass `<child-path>` as an argument. Do not `cd` into the
child. See the constraints section above for why.

### Step 6 -- post-run per-child verify

After all children are processed (or fail-fast triggered), re-run the
per-child verify loop:

```bash
uv run ai-tools standardize <child-path> --verify --json
```

for each child in execution order, aggregating the output into the
same table format as Step 4. This is the authoritative clean-state
check. If every repo is now clean, emit the success banner:

```
Workspace landline-scrubber: all 3 repos standardized
  ai-lls-lib (python/library)    PASS
  ai-lls-api (python/service)    PASS
  ai-lls-web (node/service)      PASS
```

If any drift remains, report it with a clear next action (most likely:
re-run `ai-tools standardize <child-path> --all` on the specific child,
or invoke `/ai-standardize-pipeline <child-path>` if the drift is in
the pipeline section and the umbrella returned `NEEDS_ACTION`).

### Step 7 -- consolidated workspace report

Aggregate across all children and present:

- **Baseline drift section counts** from Step 4 (how much work was
  queued at the start)
- **Per-child result summary** from Step 5 (PASS / NEEDS_ACTION / FAIL)
- **Final drift state** from Step 6
- **Follow-up actions** -- any `NEEDS_ACTION` entries (typically OIDC
  and pipeline) grouped by child, with the specific sub-skill to
  invoke per child
- **Total elapsed time** per child and overall
- **Next actions**:
  - If clean: "Workspace is standardized. Push PRs per child, or use
    `/ai-workspace-submit` for coordinated submission."
  - If drift remains: point at the specific children + sections that
    still need attention, including any per-child sub-skill invocations.

Append the workspace report to `PHASE_2_FRICTION_LOG.md` at the
workspace root as a dated entry. Create the file if it does not exist.

## Reporting

At the end of every run, regardless of success or failure, print:

- The execution order that was used
- The list of children processed and their final state
- Any per-child failures with the child name and a one-line reason
- The path to the friction log entry that was appended

Keep the report compact. The user's friction log is the durable record;
the in-terminal output is a quick-scan summary.
