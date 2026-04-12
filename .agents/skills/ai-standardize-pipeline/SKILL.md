---
name: ai-standardize-pipeline
description: AI-mediated single-file merge of `.github/workflows/pipeline.yaml` against the canonical gate vocabulary. Discovers every workflow file, classifies each by intent, surfaces every ambiguity via AskUserQuestion before making any changes, then rewrites in place preserving custom jobs, dependency wiring, parallel post-deploy patterns, and special concurrency/permissions blocks.
argument-hint: "[<repo path>]"
---

Standardize the GitHub Actions pipeline at $ARGUMENTS (defaults to cwd).

This skill is the AI-mediated half of repo standardization. The Python
layer (`ai-shell standardize pipeline ...`) is **read-only** -- it parses
the existing pipeline content, classifies jobs, and reports drift. It does
NOT write to disk. You (the AI) are the merge engine: discover, classify,
ask, then write one merged `pipeline.yaml` containing all canonical gates
inline alongside any user-custom jobs.

## Core principle: ask before acting

**Zero files are modified until every ambiguity has been explicitly
answered by the user via `AskUserQuestion`.** When in doubt, ask. The AI's
job is to recognize what it doesn't know and surface it, not to guess.
If the user aborts at any question, the skill exits with
`Standardization aborted by user at <question>. No files were modified.`
and the repo is untouched.

## Why AI not Python

Real pipelines have variability that no static merge engine can handle:
parallelized post-deploy test patterns, custom report aggregators,
ephemeral AWS test infrastructure, repo-specific deploy wiring, custom
concurrency/permissions/env blocks, and foreign projects being adopted
into the org with immature pipelines under non-canonical filenames. The
user's principle: *"this is not an easily programmable process, which is
why we're using AI."* You handle the variability. Python provides only
what is deterministic.

The output must be **one** `pipeline.yaml` file with **all canonical
gates inline as jobs** in the **same workflow DAG**. No reusable workflow
files. No fragmentation in the GitHub Actions UI.

## Inputs

- The repo root (defaults to cwd from `$ARGUMENTS`)
- `gates.json` from the `ai-standardize-repo` skill directory -- the
  canonical pre-merge gates (`Code quality`, `Security`, `Unit tests`,
  `Compliance`, `Build validation`) and post-deploy gate (`Acceptance
  tests`)
- The drift report from `ai-tools standardize <path> --area pipeline --verify --json`
- The canonical job snippets from `ai-shell standardize pipeline --print-template <Gate>` (low-level introspection)
- The minimum specs from `ai-shell standardize pipeline --print-spec <Gate>` (low-level introspection)

## Process

### Step 1 -- detect language x type

```bash
uv run ai-tools standardize <path> --verify --json
```

The drift report includes the detected language (python/node) and repo
type (library/iac). On ambiguous, ask the user via `AskUserQuestion`
and stop until they choose. Persist their answer to `ai-shell.toml`
under `[standardize]`.

### Step 2 -- discover and classify every workflow file

**Do not assume any particular filename.** A repo might use
`pipeline.yaml` (canonical), `ci.yml` (legacy), `main.yml`, `build.yml`,
or something non-standard entirely. A foreign project being adopted into
the org may have an immature pipeline under any name. This step
inventories every workflow file under `.github/workflows/` and classifies
each one by intent so Step 2.5 can surface the right questions.

**Substep 2a -- list every workflow file:**

```bash
ls <repo>/.github/workflows/
```

or use `Glob` with `<repo>/.github/workflows/*.{yml,yaml}`. If the
directory does not exist, skip to the empty-starting-state flow at the
end of Step 2.5 (first-run scaffold on an empty repo).

**Substep 2b -- `Read` each file and classify by intent.** For each
file, examine its `on:` triggers, `jobs.<id>.name` values, and `run:` /
`uses:` steps. Emit one of the following classifications:

- **pre-merge pipeline candidate** -- triggered by `pull_request:` and/or
  `push:` to `main`/`dev`, has jobs that look like canonical gates (`Code
  quality` / `Security` / `Unit tests` / `Compliance` / `Build
  validation` / `Acceptance tests`) or any legacy variant from the known
  rename map (`Pre-commit checks`, `Security scanning`, `License
  compliance`, `Validate SAM template`, `SAST scanning`, `Quality checks`,
  `Integration tests`, `Smoke tests`, `E2E *`). The canonical target
  file is `pipeline.yaml`; this classification identifies which file
  (possibly a non-canonical name) is the starting state for the merge.

- **post-merge deploy helper** -- triggered by `push:` to `main`/`dev`
  AND contains `sam deploy`, `aws s3 sync`, `aws cloudfront`, `cdk
  deploy`, `terraform apply`, or similar deploy commands. Typically
  stays as its own file.

- **post-merge publish helper** -- contains `twine upload`, `uv
  publish`, `npm publish`, `pypa/gh-action-pypi-publish`, or similar.
  Typically stays as its own file.

- **scheduled / cron** -- has `on: schedule:`. Examples: nightly
  promotion workflows, CVE review workflows, weekly dependency audits.
  Stays as-is.

- **dispatch-only** -- `on: workflow_dispatch:` only. Manual / debugging
  workflows. Stays as-is.

- **post-deploy test helper** -- triggered by `push:` with a conditional
  `if:` restricting to the dev branch, has `pytest -m integration`,
  `playwright`, or similar deployed-environment tests. These are
  candidates for the canonical `Acceptance tests` gate or for being
  preserved alongside a synthetic aggregator.

- **other** -- Renovate auto-merge enforcer, GitHub Pages publisher,
  custom automation, or anything you cannot classify confidently. Stays
  as-is; surface it in Step 2.5 as an explicit ask.

**Substep 2c -- emit a classification report** to the user before any
writes happen. **For every post-deploy test helper and every custom
job in a pre-merge candidate, include the job's `if:` condition
verbatim** (or `(no if)` when the job has none). This matters for
Step 2.5 question 5: when you propose a synthetic `Acceptance tests`
aggregator over parallel test jobs, the aggregator's own `if:` has to
be consistent with the aggregated jobs' conditions -- you cannot wire a
`push && ref == refs/heads/dev` aggregator over a job that only runs
on `pull_request`, or vice versa. Without this information up front,
you will either (a) guess wrong and ask an unnecessary follow-up, or
(b) silently widen/narrow the effective trigger when you write the
aggregator (S10-3):

```
Workflow discovery in <repo>:
  .github/workflows/ci.yml         -> pre-merge pipeline candidate (9 jobs)
    jobs:
      pre-commit          : name="Pre-commit checks"    if=(no if)
      security-scan       : name="Security scanning"    if=(no if)
      unit-tests          : name="Unit tests"           if=(no if)
      license-compliance  : name="License compliance"   if=(no if)
      deploy-test-stack   : name="Deploy test stack"    if="github.event_name == 'push' && github.ref == 'refs/heads/dev'"
      integration-tests   : name="Integration tests"    if="github.event_name == 'push' && github.ref == 'refs/heads/dev'"  needs=[deploy-test-stack]
      e2e-payment         : name="E2E Payment Tests"    if="github.event_name == 'push' && github.ref == 'refs/heads/dev'"
      e2e-admin           : name="E2E Admin Tests"      if="github.event_name == 'push'"  # broader than the others
      publish-reports     : name="Publish CI Reports"   if="github.event_name == 'push' && github.ref == 'refs/heads/dev'"
  .github/workflows/deploy.yml     -> post-merge deploy helper (sam deploy to staging/prod)
  .github/workflows/promote.yml    -> scheduled cron (promotes dev -> main nightly)
  .github/workflows/cve-review.yml -> scheduled cron (quarterly CVE review)

Canonical pipeline target: .github/workflows/pipeline.yaml
  Currently: missing
  Will use ci.yml as the starting state after user confirms in Step 2.5.

Post-deploy `if:` consistency check:
  integration-tests, e2e-payment, e2e-admin, publish-reports share
  `if:` "push && refs/heads/dev", EXCEPT e2e-admin which uses the
  broader "push" only. Surface this in Step 2.5 question 5 before
  proposing an aggregator `if:`.
```

Read each relevant job body carefully enough to capture its `if:`
line. Do not truncate or normalize the expression — the aggregator
has to match it exactly.

### Step 2.5 -- surface ambiguities and non-standard patterns via AskUserQuestion

**This is the ask-before-acting gate.** After classification, walk every
decision point where you would otherwise have to guess and pause via
`AskUserQuestion`. Do NOT write any files, invoke any sub-commands, or
call `ai-shell standardize pipeline --print-template` as anything other
than a reference read until every question is answered.

**Ambiguities to surface:**

1. **Multiple pre-merge pipeline candidates.**
   > I found two files that look like pre-merge pipelines: `ci.yml` (9
   > jobs) and `pipeline.yaml` (5 jobs). Which should I use as the
   > starting state? [a] ci.yml, [b] pipeline.yaml, [c] merge both (I'll
   > describe conflicts), [d] abort.

2. **Non-canonical filename for the chosen candidate.** Even when
   obvious, ask:
   > Found `ci.yml` as the pre-merge pipeline. After merging canonical
   > gates, I'll write to `pipeline.yaml` (canonical filename) and
   > delete `ci.yml`. OK? [a] Yes, rename to pipeline.yaml and delete
   > ci.yml. [b] Keep the existing filename (`ci.yml`). [c] Abort.

3. **Legacy gate names that look renameable.** For each legacy-name
   match:
   > Found `Pre-commit checks` -- this looks like the canonical `Code
   > quality` gate. Rename the job to `code-quality` / `Code quality`
   > and replace the body with the canonical template? Your existing
   > `needs:` wiring will be preserved. [a] Rename and replace body. [b]
   > Rename but keep the existing body. [c] Leave as custom, don't
   > treat as canonical. [d] Abort.

4. **Custom jobs that look like non-standard patterns.** For each
   unrecognized custom job, describe its intent (read the job body to
   understand what it does) and ask:
   > `deploy-test-stack` -- runs `sam deploy --stack-name
   > test-{{github.run_id}}` against a testing AWS account. This looks
   > like ephemeral AWS test infrastructure for a library repo. I'll
   > preserve it as a custom job and wire the canonical `Unit tests`
   > gate to run after it. OK? [a] Preserve and wire as described. [b]
   > Preserve but don't touch Unit tests wiring. [c] Delete this job.
   > [d] Abort.

   > `publish-ci-reports` -- aggregates coverage + bandit + semgrep +
   > compliance reports into a GitHub Pages site. I'll preserve it as a
   > custom job running on push to main. OK?

   > `integration-tests` -- runs `pytest -m integration` against the
   > ephemeral test stack. For library repos this is unusual but
   > legitimate (ephemeral test infra, not production deploy).
   > Canonical `Acceptance tests` lives on iac repos only. [a] Preserve
   > as custom, no Acceptance tests gate (recommended for library). [b]
   > Rename to `Acceptance tests` (treat as iac). [c] Abort.

5. **Parallelized post-deploy test patterns.** When multiple custom jobs
   all depend on a deploy job and run Playwright/pytest/etc. against the
   deployed environment:
   > Found 4 jobs (`e2e-smoke`, `e2e-payment`, `e2e-admin`, `e2e-bulk`)
   > that all depend on `build-and-deploy` and run Playwright against
   > the deployed environment. Options: [a] Insert a synthetic
   > `Acceptance tests` aggregator that depends on all 4 and satisfies
   > the iac_production ruleset's required check (recommended --
   > preserves your parallel structure). [b] Rename one of them to
   > `Acceptance tests` and wire the others as its deps. [c] Leave them
   > alone and skip the canonical `Acceptance tests` gate (the
   > iac_production ruleset will fail). [d] Abort.

   The synthetic aggregator pattern. **The body must include
   `actions/checkout` and `aws-actions/configure-aws-credentials` even
   though the job is logically a no-op** -- the canonical
   `Acceptance tests` minimum spec requires both steps, and
   `ai-shell standardize pipeline --validate` will report
   `spec_failures` without them even when the `needs:` wiring is
   correct. The `echo` trailer just declares success after the
   aggregated jobs all pass (S10-1):

   ```yaml
   acceptance-tests:
     name: Acceptance tests
     needs: [e2e-smoke, e2e-payment, e2e-admin, e2e-bulk]
     runs-on: ubuntu-latest
     if: github.event_name == 'push' && github.ref == 'refs/heads/dev'
     permissions:
       contents: read
       id-token: write
     steps:
       - name: Checkout
         uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6.0.2
       - name: Configure AWS credentials
         uses: aws-actions/configure-aws-credentials@e3dd6a429d7300a6a4c196c26e071d42e0343502  # v4
         with:
           role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_STAGING }}
           aws-region: ${{ vars.AWS_REGION || 'us-east-1' }}
       - name: All post-deploy tests passed
         run: echo "all post-deploy tests passed"
   ```

   **S10-4: Inspect the repo's credential pattern before writing.**
   The example above defaults to `secrets.AWS_DEPLOY_ROLE_STAGING`, but
   many repos use a different pattern:

   - `${{ env.PIPELINE_EXECUTION_ROLE }}` set via a "Set AWS environment
     variables" step that reads from `${{ vars.STAGING_PIPELINE_EXECUTION_ROLE }}`
   - `${{ secrets.AWS_DEPLOY_ROLE_STAGING }}` (direct secret reference)
   - `${{ vars.AWS_DEPLOY_ROLE }}` (variable, not secret)

   **Before generating the aggregator, `Read` the existing pipeline's
   `configure-aws-credentials` steps and mirror the same pattern.** If
   the repo uses `env.PIPELINE_EXECUTION_ROLE`, add a preceding step
   that writes it to `$GITHUB_ENV` (copy from the repo's deploy job).
   If neither exists (new repo with no deploy history), use the
   `secrets.AWS_DEPLOY_ROLE_STAGING` default above.

   **S10-5: Handle dynamic AWS_REGION the same way.** Some repos set
   `AWS_REGION` at workflow scope; others (with staging vs production
   regions) define `STAGING_AWS_REGION` / `PROD_AWS_REGION` and write
   `AWS_REGION` to `$GITHUB_ENV` in a per-job setup step. If the
   acceptance-tests aggregator uses the per-job pattern, include
   `echo "AWS_REGION=${{ env.STAGING_AWS_REGION }}" >> $GITHUB_ENV`
   in the env-setup step. **Mirror the full env-setup block from the
   deploy job the aggregator follows** rather than inventing a
   simplified subset.

6. **Top-level customizations to preserve.** Read the existing file's
   top-level keys (`name`, `on`, `env`, `concurrency`, `permissions`)
   and ask:
   > The existing `ci.yml` has these top-level keys I'll preserve:
   > `env.AWS_REGION`, `env.TEST_STACK_NAME`,
   > `concurrency.cancel-in-progress: false`, `permissions.id-token:
   > write`. Preserve all? (recommended) [a] Yes, preserve all. [b]
   > Preserve some (I'll list them). [c] Discard all and use canonical
   > defaults. [d] Abort.

7. **Spec-failing canonical jobs.** If a canonical job exists but fails
   its minimum spec:
   > `Unit tests` is present but the job is missing the coverage floor
   > step (`--cov-fail-under=80`). [a] Insert the missing step and
   > preserve the rest. [b] Replace the entire body with the canonical
   > template. [c] Leave the drift and abort standardization.

8. **Dangerous or uncertain workflows.** For any file you could not
   classify confidently, surface it:
   > Found `.github/workflows/release.yml` that publishes to PyPI via
   > `pypa/gh-action-pypi-publish`. I classified it as a post-merge
   > publish helper and do not plan to modify it. Confirm I should
   > leave it alone? [a] Yes, leave alone. [b] This is actually my
   > pre-merge pipeline -- use it as the starting state. [c] Abort.

**Only after Step 2.5 is fully answered does Step 3 run.** If the user
aborts at any question, exit with `Standardization aborted by user at
<question>. No files were modified.` and stop.

**Empty-repo fallback.** If `.github/workflows/` does not exist or
contains no workflow files, ask one question before proceeding:
> No existing pipeline found in `.github/workflows/`. Scaffold a fresh
> canonical `pipeline.yaml` with all gates (Code quality, Security,
> Unit tests, Compliance, Build validation, Acceptance tests iac only)?
> [a] Yes, scaffold from canonical templates. [b] Abort.

### Step 3 -- run validate (structural drift report)

```bash
uv run ai-tools standardize <path> --area pipeline --verify --json
```

Combined with the classification from Step 2, this gives you:

- `present` -- canonical gates already in the candidate by name
- `missing` -- canonical gates that are not present
- `legacy_candidates` -- jobs whose `name:` matches a known legacy
  variant from the rename map
- `spec_failures` -- canonical jobs that lack required steps in the
  declared minimum spec
- `custom_jobs` -- job IDs that are neither canonical nor legacy.
  **You MUST preserve these verbatim** unless the user said otherwise
  in Step 2.5.

### Step 4 -- merge

For each canonical gate in `gates.json`:

1. **If present in `report.present` AND NOT in `report.spec_failures`** --
   leave it alone. The job already meets the canonical spec.

2. **If present in `report.spec_failures`** -- the job exists with the
   right name but is missing required steps. Follow the user's answer
   from Step 2.5 question 7 (insert missing steps / replace body /
   abort). Read the canonical template with `ai-shell standardize
   pipeline --print-template <Gate>` as reference.

3. **If a `legacy_candidates` entry exists for this gate** -- follow
   the user's answer from Step 2.5 question 3. Typical default: rename
   the job key and `name:` field, replace the body from the canonical
   template, preserve the existing `needs:` clause.

4. **If multiple legacy candidates map to the same canonical gate** --
   follow the user's answer from Step 2.5 question 5 (synthetic
   aggregator / rename one / skip).

5. **If neither present, legacy, nor spec-failed** -- the gate is
   genuinely missing. Read the canonical template via `--print-template`
   and insert it. Default `needs:` wiring: `Code quality` first;
   `Security`, `Unit tests`, `Compliance`, `Build validation` all
   default to `needs: [code-quality]`; `Acceptance tests` defaults to
   `needs: [code-quality, security, unit-tests, compliance,
   build-validation]`.

For every job ID in `report.custom_jobs`, follow the user's answer from
Step 2.5 question 4 (typical default: leave it untouched). Body,
`needs:`, `if:`, `env:`, `concurrency:`, `permissions:` -- all
preserved.

Preserve top-level keys per Step 2.5 question 6.

### Step 5 -- write the merged file

Use `Write` to write the merged content to
`<repo>/.github/workflows/pipeline.yaml`. Single file. All jobs inline.
No reusable workflow files (`_gate-*.yaml`).

If Step 2.5 question 2 confirmed a rename (e.g. `ci.yml` -> `pipeline.yaml`),
delete the old file via `Bash rm` after the new one is written.

**S10-6: For Node repos, run Prettier on every written file.** Node
repos enforce `format:check` in CI. Tool-generated YAML, JSON, and
JSON5 files will fail Prettier unless formatted after writing:

```bash
npx prettier --write <repo>/.github/workflows/pipeline.yaml
```

Run this immediately after the `Write` step. If the repo has a
`format` script in `package.json`, running `npm run format` once
across all written files at the commit step also works. The key
constraint is: **no file written by any standardization skill should
reach CI without having been formatted by the repo's own formatter.**

### Step 6 -- re-validate and iterate

Re-run `ai-tools standardize <path> --area pipeline --verify --json`. If
`is_clean` is true, report success.

If still drifted, identify what's still missing and iterate. Cap at 4
total iterations (initial + 3 retries) -- if still drifted on the 5th
read, abort with a clear error and the latest report so the user can
intervene manually.

## Worked example 1: ai-lls-lib (python library with SAM test infra)

**Initial state** -- `pipeline.yaml` has these jobs:

- `pre-commit` (`name: Pre-commit checks`)
- `security-scan` (`name: Security scanning`)
- `unit-tests` (`name: Unit tests`) -- already canonical
- `compliance-reports` (`name: License compliance`)
- `deploy-test-infrastructure`, `integration-tests` -- custom test infra
  (ephemeral AWS SAM stack)
- `release`, `publish-to-pypi`, `docs` -- custom

**Discovery report (Step 2):**

```
Workflow discovery in ai-lls-lib:
  .github/workflows/pipeline.yaml -> pre-merge pipeline candidate (9 jobs)
  (no other workflow files)

Classification of pipeline.yaml:
  Pre-commit checks            -> legacy candidate for 'Code quality'
  Security scanning            -> legacy candidate for 'Security'
  Unit tests                   -> already canonical
  License compliance           -> legacy candidate for 'Compliance'
  deploy-test-infrastructure   -> custom (ephemeral AWS test stack)
  integration-tests            -> custom (pytest against test stack)
  release                      -> custom (python-semantic-release on main)
  publish-to-pypi              -> custom (pypa/gh-action-pypi-publish)
  docs                         -> custom (pdoc to GitHub Pages)

Missing canonical gates: Compliance (legacy candidate exists), Build validation
```

**Ask-before-acting loop (Step 2.5):**

> Question 1 of 4: I'll rename the legacy gates (Pre-commit checks ->
> Code quality, Security scanning -> Security, License compliance ->
> Compliance) and replace their bodies with the canonical templates,
> preserving their `needs:` clauses. Insert `Build validation` as a new
> gate depending on `code-quality`. OK? [a] Yes, proceed. [b] Keep
> legacy names. [c] Abort.

> Question 2 of 4: The `deploy-test-infrastructure` -> `integration-tests`
> pattern looks like ephemeral AWS test infrastructure for this library.
> For library repos this is unusual but legitimate. I plan to preserve
> both jobs as custom and NOT insert the canonical `Acceptance tests`
> gate (libraries don't require one). Is that correct? [a] Preserve as
> custom, no Acceptance tests (recommended for library). [b] Preserve
> AND also insert a synthetic `Acceptance tests` gate. [c] Rename
> `integration-tests` -> `Acceptance tests` (treat as iac). [d] Abort.

> Question 3 of 4: Found `release`, `publish-to-pypi`, `docs` jobs that
> handle semantic-release, PyPI publish, and pdoc deploy. I'll preserve
> all three as custom jobs and leave their `needs:` clauses alone. OK?

> Question 4 of 4: Top-level customizations to preserve:
> `env.TEST_STACK_NAME`, `concurrency.cancel-in-progress: false` (safe
> for iac test infra), `permissions.id-token: write`. OK to preserve
> all?

Only after all four questions are answered does the merge run and the
file get written.

## Worked example 2: ai-lls-api (ci.yml + Integration/Smoke split)

**Initial state**: `ci.yml` (not `pipeline.yaml`) with jobs including
`integration-tests` (`name: Integration tests`) and `smoke-tests` (`name:
Smoke tests`), plus custom `deploy-staging` and `Publish CI reports`.

**Ask-before-acting loop:**

> Question 1: Found `ci.yml` as the pre-merge pipeline. After merging
> canonical gates, I'll write to `pipeline.yaml` and delete `ci.yml`.
> OK?

> Question 2: Two jobs match the canonical `Acceptance tests` gate:
> `integration-tests` and `smoke-tests`. Options: [a] Insert a synthetic
> aggregator that depends on both (recommended). [b] Rename one to
> `Acceptance tests` (which one?). [c] Abort.

Whatever the user picks, the result is one `pipeline.yaml` with the
canonical gates inline and the user's parallel test structure preserved.

## Worked example 3: ai-lls-web (4 parallel E2E jobs)

**Initial state**: 4 custom jobs `e2e-smoke`, `e2e-payment`,
`e2e-admin`, `e2e-bulk` (each `name: E2E * Tests`), no canonical
`Acceptance tests` gate.

**Ask-before-acting loop:**

> Question: 4 jobs match the canonical `Acceptance tests` gate:
> `e2e-smoke`, `e2e-payment`, `e2e-admin`, `e2e-bulk`. Insert a
> synthetic `Acceptance tests` aggregator that depends on all four
> (recommended -- preserves parallel structure), or rename one of
> them?

User picks aggregator. AI inserts (note the `checkout` +
`configure-aws-credentials` steps are required by the canonical
`Acceptance tests` spec even though the job is logically a no-op; see
Step 2.5 question 5 for rationale):

```yaml
acceptance-tests:
  name: Acceptance tests
  needs: [e2e-smoke, e2e-payment, e2e-admin, e2e-bulk]
  runs-on: ubuntu-latest
  if: github.event_name == 'push' && github.ref == 'refs/heads/dev'
  permissions:
    contents: read
    id-token: write
  steps:
    - name: Checkout
      uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6.0.2
    - name: Configure AWS credentials
      uses: aws-actions/configure-aws-credentials@e3dd6a429d7300a6a4c196c26e071d42e0343502  # v4
      with:
        role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_STAGING }}
        aws-region: ${{ vars.AWS_REGION || 'us-east-1' }}
    - name: All post-deploy tests passed
      run: echo "all post-deploy tests passed"
```

The 4 E2E jobs are left untouched.

## Constraints

- **Single file output.** Never write `_gate-*.yaml` reusable workflow
  files. Pipeline standardization is one inline file. Period.
- **Custom jobs are sacred.** Anything in `report.custom_jobs` is
  preserved verbatim unless the user explicitly said otherwise in Step
  2.5.
- **Job IDs follow canonical slugs.** When renaming a legacy job, the
  YAML map key becomes the lowercased hyphenated gate name
  (`code-quality:`, `security:`, `unit-tests:`, `compliance:`,
  `build-validation:`, `acceptance-tests:`). The `name:` field becomes
  the exact canonical gate string.
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
- **Zero files are modified** until every question from Step 2.5 is
  answered. If the user aborts at any point, exit with
  `Standardization aborted by user. No files were modified.` and the
  repo is untouched.

Report:

- Count of canonical gates added / preserved / renamed
- Count of custom jobs preserved
- Final `is_clean` status from the second validate run
- List of any iterations needed to reach clean
- Any files that were renamed or deleted (e.g. `ci.yml` -> `pipeline.yaml`)
