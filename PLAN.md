# PLAN

## Objective

Update this repository so `ai-shell` scaffolds, documents, and uses the modernized `ai-tools` workflow model defined in [ai-tools.md](./ai-tools.md).

This repo is **not** the implementation home for the `ai-tools` CLI itself. This repo should:

- declare the new workflow contract clearly
- scaffold notes and skills that call the right `ai-tools` commands
- remove stale or duplicated workflow logic from skills over time
- keep tests aligned with the new command surface and naming

The `ai-tools` implementation work belongs in the `augint-tools` / `ai-tools` repo.

## Direct Answer To The Open Question

Yes: `ai-tools` is supposed to implement the command surface and behavior described in [ai-tools.md](./ai-tools.md).

Not necessarily all in one shot, but that file is the intended implementation spec for `ai-tools`, with:

- `repo` workflow commands
- `mono` workflow commands
- `standardize` workflow commands
- shared detection/output/filtering contracts
- the P0/P1/P2 rollout priorities

This repo should then be updated to consume that implemented surface.

## Scope Split

### Workstream A: `ai-tools` repo

External dependency. Implement the new CLI surface described in [ai-tools.md](./ai-tools.md):

- `ai-tools repo ...`
- `ai-tools mono ...`
- `ai-tools standardize ...`

This is required before the final thin-skill model is truly complete.

### Workstream B: this repo (`augint-shell`)

Update scaffolding, notes, templates, and tests so generated agent environments:

- reference `ai-tools` consistently
- use `ai-tools mono` consistently for workspace workflows
- move toward thin wrapper skills for repo and standardize workflows
- stop teaching stale `ai-tools mono` / `augint-tools` / shell-heavy hybrids

This PLAN covers **Workstream B**, while documenting dependencies on Workstream A.

## Current State Summary

### What is already good

- Workspace skills under `src/ai_shell/templates/*/skills/ai-workspace-*` are already mostly thin wrappers.
- The repo now has [ai-tools.md](./ai-tools.md) as the new execution spec.
- `scaffold.py` already distinguishes `library`, `service`, and `workspace` and installs different skill sets.

### What is still wrong

#### 1. Naming drift

There is an inconsistent mix of:

- `augint-tools`
- `ai-tools`
- `ai-tools mono`

Current state:

- notes and tests still mention `ai-tools mono`
- workspace skill templates currently mention `augint-tools ...`
- the new spec says the project is `augint-tools` but the command should be `ai-tools`

This must be normalized.

#### 2. Repo skills still carry too much workflow logic

These source templates are still shell-heavy and should eventually become thin wrappers around `ai-tools repo`:

- `src/ai_shell/templates/agents/skills/ai-status/SKILL.md`
- `src/ai_shell/templates/agents/skills/ai-pick-issue/SKILL.md`
- `src/ai_shell/templates/agents/skills/ai-prepare-branch/SKILL.md`
- `src/ai_shell/templates/agents/skills/ai-submit-work/SKILL.md`
- `src/ai_shell/templates/agents/skills/ai-monitor-pipeline/SKILL.md`
- `src/ai_shell/templates/agents/skills/ai-promote/SKILL.md`
- `src/ai_shell/templates/agents/skills/ai-rollback/SKILL.md`
- `src/ai_shell/templates/agents/skills/ai-repo-health/SKILL.md`

The corresponding Claude templates under `src/ai_shell/templates/claude/skills/` must stay aligned too.

#### 3. Standardize workflow is still prose-driven

The unified `ai-standardize-repo` skill still embeds the standardization logic as prose instead of delegating to a deterministic tool surface.

#### 4. Notes and institutional guidance are stale

These templates still teach the old contract:

- `src/ai_shell/templates/notes.md`
- `src/ai_shell/templates/notes-workspace.md`
- `src/ai_shell/templates/notes-library.md`
- `src/ai_shell/templates/notes-service.md`

#### 5. Tests still assert old strings

Likely impacted tests include:

- `tests/unit/test_notes_merge.py`
- `tests/unit/test_scaffold.py`

Additional tests may need to be added for new template wording.

## Desired End State For This Repo

After the work is complete:

1. Generated notes teach:
   - `ai-tools repo ...` for normal repo workflows
   - `ai-tools mono ...` for workspace workflows
   - `ai-tools standardize ...` for standardization workflows

2. Generated skills are thin wrappers wherever the corresponding `ai-tools` command exists.

3. Skill text no longer embeds large procedural shell workflows that belong in `ai-tools`.

4. Source-of-truth docs are clear:
   - [ai-tools.md](./ai-tools.md) is the command spec
   - [augint-tools.md](./augint-tools.md) is background/product-direction context

5. Scaffolded output and tests are aligned with the new contract.

## Source Of Truth Rules

When implementing this plan, treat these as authoritative:

- [ai-tools.md](./ai-tools.md): command/workflow spec
- [src/ai_shell/scaffold.py](./src/ai_shell/scaffold.py): scaffold behavior and installed skill sets
- `src/ai_shell/templates/**`: source templates for scaffolded output

Do **not** treat the repo-root `.agents/skills/*` copies as the primary source for scaffolding changes. The scaffold source of truth is under `src/ai_shell/templates/`.

## Implementation Strategy

Use a phased migration so this repo can move ahead cleanly even if `ai-tools` lands in pieces.

## Phase 1: Normalize Naming And Docs

### Goal

Remove command-surface ambiguity first.

### Changes

1. Update notes templates to consistently say:
   - `ai-tools repo ...` for normal repo commands
   - `ai-tools mono ...` for workspace commands
   - `ai-tools standardize ...` for standardization commands

2. Update institutional guidance wording in:
   - `src/ai_shell/templates/notes.md`
   - `src/ai_shell/templates/notes-workspace.md`
   - `src/ai_shell/templates/notes-library.md`
   - `src/ai_shell/templates/notes-service.md`

3. Keep the wording aligned with [ai-tools.md](./ai-tools.md):
   - `augint-tools` = project/repo name
   - `ai-tools` = command users and skills run

4. Update tests asserting old strings.

### Acceptance Criteria

- No scaffolded note template teaches `augint-tools ...` as the command.
- No scaffolded note template teaches plain root-level `ai-tools status` / `ai-tools submit` as the primary normal-repo contract.
- Workspace notes teach `ai-tools mono ...`.
- Tests pass with the new wording.

## Phase 2: Convert Workspace Skills To Final Command Contract

### Goal

Finish the mono/workspace side first because it is already closest.

### Changes

Update these source templates in both `agents` and `claude` trees:

- `ai-workspace-init`
- `ai-workspace-sync`
- `ai-workspace-status`
- `ai-workspace-pick`
- `ai-workspace-branch`
- `ai-workspace-test`
- `ai-workspace-lint`
- `ai-workspace-submit`
- `ai-workspace-update`
- `ai-workspace-health`
- `ai-workspace-foreach`

### Required adjustments

1. Change command text from `augint-tools ...` to `ai-tools mono ...`.

2. Align each skill to the mapping in [ai-tools.md](./ai-tools.md), for example:
   - status -> `ai-tools mono status --json`
   - test -> `ai-tools mono check --phase tests --json`
   - lint -> `ai-tools mono check --phase quality --json`
   - health -> `ai-tools mono status --actionable --json`

3. Keep them thin:
   - call the tool
   - summarize the structured output
   - do not re-encode dependency or branch logic in the skill prose

### Acceptance Criteria

- Workspace skills are all consistent with `ai-tools mono`.
- No workspace skill contains stale `augint-tools` command text.
- Skills remain compact wrappers.

## Phase 3: Introduce Thin Repo Workflow Skills

### Goal

Refactor repo skills to delegate to `ai-tools repo` instead of carrying procedural shell logic.

### Target skill mappings

Per [ai-tools.md](./ai-tools.md):

- `ai-status` -> `ai-tools repo status --json`
- `ai-pick-issue` -> `ai-tools repo issues pick --json`
- `ai-prepare-branch` -> `ai-tools repo branch prepare --json`
- `ai-submit-work` -> `ai-tools repo submit --json`
- `ai-monitor-pipeline` -> `ai-tools repo ci watch --json` or `ci triage --json`
- `ai-promote` -> `ai-tools repo promote --json`
- `ai-rollback` -> `ai-tools repo rollback plan/apply --json`
- `ai-repo-health` -> `ai-tools repo health --json`

### Important dependency

This phase depends on `ai-tools` implementing enough of the repo surface to be callable.

### Migration recommendation

Do this in two steps:

#### Step 3A: transitional rewrite

Before all commands exist, update skill prose so it:

- references the intended `ai-tools repo` command first
- clearly states fallback behavior only if the command is not yet available
- minimizes shell logic where possible

#### Step 3B: final thin wrappers

Once `ai-tools` implements the commands:

- remove the embedded shell algorithms
- keep only command invocation + summary/reporting guidance

### Acceptance Criteria

- Repo skills no longer teach large shell workflows as the primary path.
- Final state is thin wrapper skills around `ai-tools repo`.

## Phase 4: Convert Standardize Skills To `ai-tools standardize`

### Goal

Make the standardize workflow tool-first and deterministic.

### Target command mappings

- `ai-standardize-repo` -> `ai-tools standardize audit/fix/verify`
- dotfiles concerns -> `ai-tools standardize audit --section dotfiles`
- quality/pre-commit concerns -> `ai-tools standardize audit --section quality`
- pipeline concerns -> `ai-tools standardize audit --section pipeline`
- renovate concerns -> `ai-tools standardize audit --section renovate`
- release concerns -> `ai-tools standardize audit --section release`

### Repo-specific change decision

This repo currently scaffolds the unified `ai-standardize-repo` skill and treats the old specialized standardize skills as deleted/stale via `src/ai_shell/scaffold.py`.

Recommended direction:

- keep the unified `ai-standardize-repo` skill as the primary scaffolded entrypoint
- optionally add thin sectional aliases later only if they materially help UX
- do not reintroduce the old shell-heavy specialized skills as scaffold defaults

### Changes

1. Rewrite `ai-standardize-repo` in both template trees as a thin wrapper over `ai-tools standardize`.
2. Update any references in `ai-new-project` and related docs that still assume direct shell/prose standardization logic.
3. Keep `scaffold.py` deletion behavior for obsolete standardize skills unless there is a deliberate product decision to restore them as thin aliases.

### Acceptance Criteria

- Standardize workflow documentation points to `ai-tools standardize`.
- Unified standardize skill is thin and tool-first.
- No major standardization rule remains solely encoded in skill prose.

## Phase 5: Update Init/New-Project Messaging

### Goal

Ensure bootstrap flows teach the correct command surface from day one.

### Files to update

- `src/ai_shell/templates/agents/skills/ai-init/SKILL.md`
- `src/ai_shell/templates/claude/skills/ai-init/SKILL.md`
- `src/ai_shell/templates/agents/skills/ai-new-project/SKILL.md`
- `src/ai_shell/templates/claude/skills/ai-new-project/SKILL.md`

### Changes

1. `ai-init` should explain:
   - workspace repos get `ai-workspace-*` skills and use `ai-tools mono`
   - normal repos use `ai-tools repo`
   - standardization flows use `ai-tools standardize`

2. `ai-new-project` should stop implying that standardization logic lives mainly in skill prose.

3. Any command examples should align with the new contract.

### Acceptance Criteria

- Freshly initialized repos receive correct guidance with no command-surface ambiguity.

## Phase 6: Update Tests

### Goal

Lock the new contract into tests so it does not drift again.

### Minimum test updates

1. Update assertions in:
   - `tests/unit/test_notes_merge.py`
   - `tests/unit/test_scaffold.py`

2. Add or extend tests to cover:
   - normal repo notes mention `ai-tools repo`
   - workspace notes mention `ai-tools mono`
   - standardization guidance mentions `ai-tools standardize`
   - workspace skill templates no longer reference `augint-tools`

3. Add template-content regression coverage where practical so naming drift is caught early.

### Acceptance Criteria

- Tests directly assert the new command surface.

## Optional Follow-Up Phase: CLI Helpers In This Repo

This is optional and lower priority.

If useful, this repo may later add helper validation or lint checks to ensure scaffold templates reference only approved command surfaces. For example:

- a unit test helper that scans templates for banned strings
- a scaffold validation command

This is optional because ordinary unit tests may already be sufficient.

## External Dependencies On `ai-tools`

These are the `ai-tools` capabilities this repo expects to exist eventually.

### P0 expected before final thin-wrapper migration

- shared detection engine
- `ai-tools repo status`
- `ai-tools repo branch prepare`
- `ai-tools repo check plan`
- `ai-tools repo check run`
- `ai-tools repo submit`
- `ai-tools repo ci watch`
- `ai-tools repo ci triage`
- `ai-tools standardize detect`
- `ai-tools standardize audit`
- `ai-tools standardize fix`
- `ai-tools standardize verify`
- `ai-tools mono inspect`
- `ai-tools mono check`
- improved `ai-tools mono status`

### P1 expected next

- `ai-tools repo issues pick`
- `ai-tools repo promote`
- `ai-tools repo rollback`
- `ai-tools mono graph`
- improved `ai-tools mono update`
- improved `ai-tools mono submit --monitor`

### P2 expected later

- `ai-tools repo health`
- further GitHub provider abstractions for standardize

## Recommended Order Of Execution

If implementing this repo only:

1. Phase 1: naming/docs
2. Phase 2: workspace skills
3. Phase 5: init/new-project messaging
4. Phase 6: tests
5. Phase 3 and 4 as `ai-tools` capabilities land

If implementing both repos in parallel:

1. `ai-tools` P0 commands
2. this repo Phase 1 + 2 + 5 + 6
3. this repo Phase 3 + 4
4. `ai-tools` P1 and P2

## Concrete File Targets In This Repo

### Must update

- [ai-tools.md](./ai-tools.md) if the command spec evolves
- [augint-tools.md](./augint-tools.md) only for positioning / pointer text
- [src/ai_shell/templates/notes.md](./src/ai_shell/templates/notes.md)
- [src/ai_shell/templates/notes-workspace.md](./src/ai_shell/templates/notes-workspace.md)
- [src/ai_shell/templates/notes-library.md](./src/ai_shell/templates/notes-library.md)
- [src/ai_shell/templates/notes-service.md](./src/ai_shell/templates/notes-service.md)
- [src/ai_shell/templates/agents/skills/ai-init/SKILL.md](./src/ai_shell/templates/agents/skills/ai-init/SKILL.md)
- [src/ai_shell/templates/claude/skills/ai-init/SKILL.md](./src/ai_shell/templates/claude/skills/ai-init/SKILL.md)
- [src/ai_shell/templates/agents/skills/ai-new-project/SKILL.md](./src/ai_shell/templates/agents/skills/ai-new-project/SKILL.md)
- [src/ai_shell/templates/claude/skills/ai-new-project/SKILL.md](./src/ai_shell/templates/claude/skills/ai-new-project/SKILL.md)
- all `src/ai_shell/templates/*/skills/ai-workspace-*/SKILL.md`
- repo workflow skills in both `agents` and `claude` template trees
- [src/ai_shell/templates/agents/skills/ai-standardize-repo/SKILL.md](./src/ai_shell/templates/agents/skills/ai-standardize-repo/SKILL.md)
- [src/ai_shell/templates/claude/skills/ai-standardize-repo/SKILL.md](./src/ai_shell/templates/claude/skills/ai-standardize-repo/SKILL.md)
- [tests/unit/test_notes_merge.py](./tests/unit/test_notes_merge.py)
- [tests/unit/test_scaffold.py](./tests/unit/test_scaffold.py)

### Likely review-only, not major edits

- [src/ai_shell/scaffold.py](./src/ai_shell/scaffold.py)

`scaffold.py` likely does not need major logic changes unless we decide to alter installed skill sets or add new scaffolded aliases.

## Non-Goals

Do not do these as part of this repo plan unless requirements change:

- implement the `ai-tools` CLI itself here
- reintroduce the deleted shell-heavy specialized standardize skills by default
- create parallel, duplicated workflow logic in both skills and `ai-tools`
- preserve stale `augint-tools` command text just for backward familiarity

## Implementation Notes For Whoever Picks This Up

1. Start from [ai-tools.md](./ai-tools.md), not from the old skill prose.
2. Prefer changing template sources under `src/ai_shell/templates/`, not generated copies.
3. Keep skills terse and directive once the command exists.
4. If `ai-tools` support is partial, document fallback behavior explicitly and temporarily.
5. Every wording change that affects scaffolded content should get a test update.

## Definition Of Done

This repo portion is done when:

- scaffolded notes consistently teach `ai-tools repo`, `ai-tools mono`, and `ai-tools standardize`
- workspace skills are fully aligned to `ai-tools mono`
- repo and standardize skills are rewritten to delegate to `ai-tools` as commands become available
- tests enforce the new contract
- there is no material naming drift left between docs, skill templates, and tests
