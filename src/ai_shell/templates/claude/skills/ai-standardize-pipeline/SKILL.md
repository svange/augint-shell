---
name: ai-standardize-pipeline
description: AI-mediated single-file merge of `.github/workflows/pipeline.yaml` against the canonical gate vocabulary. Reads the existing pipeline, runs a read-only drift report, then rewrites in place preserving custom jobs, dependency wiring, parallel post-deploy patterns, and special concurrency/permissions blocks.
argument-hint: "[<repo path>]"
---

Standardize the GitHub Actions pipeline at $ARGUMENTS (defaults to cwd).

This skill is the AI-mediated half of repo standardization. The Python
layer (`ai-shell standardize pipeline ...`) is **read-only** -- it parses
the existing `pipeline.yaml`, classifies jobs, and reports drift. It does
NOT write to disk. You (the AI) are the merge engine: read the report,
read the canonical job snippets as reference, then write one merged
`pipeline.yaml` containing all canonical gates inline alongside any
user-custom jobs.

## Why AI not Python

Real pipelines have variability that no static merge engine can handle:
parallelized post-deploy test patterns, custom report aggregators,
ephemeral test infra jobs, repo-specific deploy wiring, custom
concurrency/permissions/env blocks. The user's principle: *"this is not
an easily programmable process, which is why we're using AI."* You handle
the variability. Python provides only what's deterministic.

The output must be **one** `pipeline.yaml` file with **all canonical
gates inline as jobs** in the **same workflow DAG**. No reusable
workflow files. No fragmentation in the GitHub Actions UI.

## Inputs

- The repo root (defaults to cwd from `$ARGUMENTS`)
- `gates.json` from the `ai-standardize-repo` skill directory -- the
  canonical pre-merge gates (`Code quality`, `Security`, `Unit tests`,
  `Compliance`, `Build validation`) and post-deploy gate (`Acceptance
  tests`)
- The drift report from `ai-shell standardize pipeline --validate --json`
- The canonical job snippets from `ai-shell standardize pipeline --print-template <Gate>`
- The minimum specs from `ai-shell standardize pipeline --print-spec <Gate>`

## Process

### Step 1 -- detect

```bash
uv run ai-shell standardize detect --json <repo>
```

Note the language (python/node) and repo type (library/iac). On
ambiguous, ask the user via `AskUserQuestion` and stop until they
choose. Persist their answer to `ai-shell.toml` under `[standardize]`.

### Step 2 -- read existing pipeline

Use `Read` on `<repo>/.github/workflows/pipeline.yaml`. If absent, note
that and skip to Step 4 with an empty starting state.

### Step 3 -- run validate

```bash
uv run ai-shell standardize pipeline --validate --json <repo>
```

The structured report has:

- `present` -- canonical gates already in the pipeline by name
- `missing` -- canonical gates that are not present
- `legacy_candidates` -- jobs whose `name:` matches a known legacy
  variant (`Pre-commit checks` -> `Code quality`, `Security scanning` ->
  `Security`, `Integration tests` / `Smoke tests` / `E2E *` ->
  `Acceptance tests`, etc.)
- `spec_failures` -- canonical jobs that lack required steps in the
  declared minimum spec
- `custom_jobs` -- job IDs that are neither canonical nor legacy.
  **You MUST preserve these verbatim** (body, `needs:`, `if:`, `env:`,
  everything).

### Step 4 -- merge

For each canonical gate in `gates.json`:

1. **If present in `report.present` AND NOT in `report.spec_failures`** --
   leave it alone. The job already meets the canonical spec; don't touch
   the body.

2. **If present in `report.spec_failures`** -- the job exists with the
   right name but is missing required steps. Read the canonical template
   with `ai-shell standardize pipeline --print-template <Gate>`. Insert
   the missing steps in declared order, preserving any user-added steps
   that are not in the spec. Do NOT replace the entire body unless the
   drift is so severe that surgical insertion is harder than a rewrite.

3. **If a `legacy_candidates` entry exists for this gate** -- this is a
   rename. Read the canonical template via `--print-template`. Replace
   the existing job's body with the canonical template's body. **Preserve
   the user's `needs:` clause** so the dependency graph stays intact.
   Rename the job key (the YAML map key, e.g. `pre-commit-checks:` ->
   `code-quality:`) to match the canonical slug (the lowercased,
   hyphenated form of the gate name). Update the job's `name:` field to
   the exact canonical gate name.

4. **If multiple legacy candidates map to the same canonical gate** (the
   parallel post-deploy test pattern: `Integration tests` + `Smoke tests`
   both map to `Acceptance tests`, or 4 `E2E *` jobs in ai-lls-web), use
   `AskUserQuestion` to ask the user:

   > Multiple jobs match the canonical `Acceptance tests` gate:
   > [Integration tests, Smoke tests]. Choose one:
   > - Rename one of them to `Acceptance tests` (pick which)
   > - Insert a synthetic `Acceptance tests` aggregator that depends on
   >   all of them and just confirms they passed (preserves your parallel
   >   structure; satisfies the iac_production ruleset's required check)

   The synthetic aggregator pattern:

   ```yaml
   acceptance-tests:
     name: Acceptance tests
     needs: [integration-tests, smoke-tests]   # all the parallel jobs
     runs-on: ubuntu-latest
     if: github.event_name == 'push' && github.ref == 'refs/heads/dev'
     steps:
       - name: All post-deploy tests passed
         run: echo "all post-deploy tests passed"
   ```

   Default to the synthetic aggregator unless the user picks a rename --
   the synthetic version preserves the user's intent (parallelized
   testing) while still providing a single `Acceptance tests` check run
   for the iac_production ruleset to gate on.

5. **If neither present, legacy, nor spec-failed** -- the gate is
   genuinely missing. Read the canonical template via `--print-template`.
   Insert it at a sensible point in the dependency graph: default
   `needs:` to the canonical job that conventionally precedes it
   (`Code quality` first; `Security`, `Unit tests`, `Compliance`,
   `Build validation` all default to `needs: [code-quality]`;
   `Acceptance tests` defaults to `needs: [code-quality, security,
   unit-tests, compliance, build-validation]`).

For every job ID in `report.custom_jobs`, **leave it untouched**. Its
body, `needs:`, `if:`, `env:`, `concurrency:`, `permissions:` -- all
preserved. The custom jobs are user-owned and must round-trip exactly.

Preserve top-level keys (`name`, `on`, `permissions`, `concurrency`,
`env`) verbatim. If the existing pipeline has comments that YAML
round-tripping permits, preserve them.

### Step 5 -- write the merged file

Use `Write` to write the merged content back to
`<repo>/.github/workflows/pipeline.yaml`. Single file. All jobs inline.
No reusable workflow files (`_gate-*.yaml`).

### Step 6 -- re-validate and iterate

Re-run `ai-shell standardize pipeline --validate --json <repo>`. If
`is_clean` is true, you are done; report success.

If still drifted, identify what's still missing and iterate. Cap at 4
total iterations (initial + 3 retries) -- if still drifted on the 5th
read, abort with a clear error and the latest report so the user can
intervene manually.

## Worked example: ai-lls-lib (python library with SAM test infra)

**Initial state** -- `pipeline.yaml` has these jobs:

- `pre-commit` (`name: Pre-commit checks`)
- `security-scan` (`name: Security scanning`)
- `unit-tests` (`name: Unit tests`) -- already canonical
- `deploy-test-stack`, `teardown-test-stack`, `integration-tests` --
  custom test infra
- `release`, `publish-to-pypi` -- custom

**Drift report:**

- `present`: `["Unit tests"]`
- `missing`: `["Compliance", "Build validation"]`
- `legacy_candidates`: `[("pre-commit", "Pre-commit checks", "Code quality"),
  ("security-scan", "Security scanning", "Security")]`
- `custom_jobs`: `["deploy-test-stack", "teardown-test-stack",
  "integration-tests", "release", "publish-to-pypi"]`

**Merged result:**

- `code-quality` (renamed from `pre-commit`, body replaced from canonical
  python-library template, `needs:` empty)
- `security` (renamed from `security-scan`, body replaced, `needs:
  [code-quality]` preserved)
- `unit-tests` (untouched)
- `compliance` (newly inserted, `needs: [code-quality]`)
- `build-validation` (newly inserted, `needs: [code-quality]`)
- `deploy-test-stack`, `teardown-test-stack`, `integration-tests`,
  `release`, `publish-to-pypi` -- preserved verbatim

## Worked example: ai-lls-web (4 parallel E2E test jobs)

**Initial state**: 4 custom jobs `e2e-smoke`, `e2e-payment`, `e2e-admin`,
`e2e-bulk` (`name: E2E Smoke Tests`, `name: E2E Payment Tests`, etc.),
no canonical `Acceptance tests` gate.

**Drift report:**

- `legacy_candidates`: 4 entries, each mapping `E2E *` to `Acceptance
  tests`

**AI prompts the user:**

> 4 jobs match the canonical `Acceptance tests` gate: e2e-smoke,
> e2e-payment, e2e-admin, e2e-bulk. Insert a synthetic `Acceptance tests`
> aggregator that depends on all four (recommended), or rename one of
> them?

User picks the aggregator. AI inserts:

```yaml
acceptance-tests:
  name: Acceptance tests
  needs: [e2e-smoke, e2e-payment, e2e-admin, e2e-bulk]
  runs-on: ubuntu-latest
  if: github.event_name == 'push' && github.ref == 'refs/heads/dev'
  steps:
    - name: All post-deploy tests passed
      run: echo "all post-deploy tests passed"
```

The 4 E2E jobs are left untouched (they appear in `custom_jobs`).

## Worked example: ai-lls-api (Integration + Smoke split)

**Initial state**: jobs `integration-tests` (`name: Integration tests`)
and `smoke-tests` (`name: Smoke tests`), plus custom `deploy-staging`
and `Publish CI reports`.

**Drift report**: `legacy_candidates` has both `Integration tests` and
`Smoke tests` mapping to `Acceptance tests`.

**AI prompts the user**: "Rename one to `Acceptance tests` or insert
synthetic aggregator?" User picks rename of `smoke-tests` -> canonical
`acceptance-tests`. The `integration-tests` job stays as a custom job
(the AI removes it from the legacy list once `Acceptance tests` has a
home, since it's no longer the only candidate).

## Constraints

- **Single file output.** Never write `_gate-*.yaml` reusable workflow
  files. Pipeline standardization is one inline file. Period.
- **Custom jobs are sacred.** Anything in `report.custom_jobs` is
  preserved verbatim, including subtle details like custom env vars,
  concurrency groups, OIDC permissions blocks, conditional `if:`
  expressions.
- **Job IDs follow canonical slugs.** When renaming a legacy job, the YAML
  map key becomes the lowercased hyphenated gate name (`code-quality:`,
  `security:`, `unit-tests:`, `compliance:`, `build-validation:`,
  `acceptance-tests:`). The `name:` field becomes the exact canonical
  gate string.
- **Action versions are not your concern.** Renovate manages action SHA
  pins; the canonical templates ship with the current pinned SHAs but
  you don't enforce a specific version.
- **Step `name:` fields are free text.** The minimum spec only checks
  `uses:` (action repo path substring) and `run:` (regex). You can
  rename steps freely.
- **iac repos must include `Acceptance tests`.** Library repos must NOT
  include `Acceptance tests`.
- **iac `Acceptance tests` jobs must be guarded** by
  `if: github.event_name == 'push' && github.ref == 'refs/heads/dev'`
  so they only run after a dev push (not on PRs against main).

Report:

- count of canonical gates added / preserved / renamed
- count of custom jobs preserved
- final `is_clean` status from the second validate run
- the list of any iterations needed to reach clean
