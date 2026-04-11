---
name: ai-standardize-renovate
description: Detect-and-ask before writing the canonical Renovate config (renovate.json5). Surfaces custom packageRules, matchPackageNames, commitMessagePrefix overrides, and automergeStrategy deviations via AskUserQuestion before any overwrite.
argument-hint: "[<repo path>]"
---

Standardize the Renovate config at $ARGUMENTS (defaults to cwd).

## Core principle: ask before acting

Never silently overwrite custom `packageRules`, grouping rules, or
package-specific overrides the user has authored. Detect drift,
classify it, and ask via `AskUserQuestion` before writing. If the user
aborts, exit with `Standardization aborted by user. No files were
modified.`

## Process

### Step 1 -- detect language and repo type

```bash
uv run ai-tools standardize <path> --verify --json
```

The drift report includes python/node and library/iac. On ambiguous,
ask and stop.

### Step 2 -- read the existing config (if present)

`Read <repo>/renovate.json5` (or `renovate.json` if that's what the
repo uses). If absent, skip to Step 4 with one question:
> No existing `renovate.json5`. Scaffold the canonical template for
> `<language>/<type>`? [a] Yes. [b] Abort.

### Step 3 -- diff against canonical and classify

Parse the existing JSON5 and categorize every top-level key and every
entry in `packageRules` into three groups:

1. **Canonical content that matches** -- no action.
2. **Canonical content that drifted** -- plan to rewrite.
3. **Custom content** -- not in the canonical template.

**Custom content to detect:**

- **Custom `packageRules`** beyond the canonical set (the canonical set
  covers prod deps by update type, dev deps grouped, GitHub Actions
  grouped, pre-commit updates, and the python-semantic-release / node
  semantic-release package-name opt-out)
- **Custom `matchPackageNames`** entries -- specific packages pinned,
  grouped, or held at a particular major version
- **Custom `commitMessagePrefix` values** -- deviations from the
  canonical scheme (`fix(deps):` for iac prod, `chore(deps):` for
  library prod, `chore(deps-dev):` for dev deps, `ci(deps):` for GitHub
  Actions and pre-commit)
- **Custom `automergeStrategy`** overrides -- especially dangerous on
  node/iac where squash drops semantic-release `[skip ci]` markers
- **Custom `enabledManagers`** additions (e.g. `dockerfile`, `nix`)
- **Custom top-level fields** like `ignorePaths`, `extends`, `schedule`,
  `timezone`, `labels`

### Step 4 -- ask before acting

> Your existing `renovate.json5` has 4 custom `packageRules` beyond the
> canonical set:
>
> 1. `matchPackageNames: ["boto3", "botocore"]` grouped as "aws-sdk",
>    automerge: true
> 2. `matchPackageNames: ["pytest"]` with `allowedVersions: "<8.0"`
>    (pinned)
> 3. `matchDepTypes: ["devDependencies"]` with custom
>    `commitMessagePrefix: "deps(dev):"` (deviates from canonical
>    `chore(deps-dev):`)
> 4. `matchUpdateTypes: ["major"]` with `dependencyDashboardApproval: true`
>    (extra gating)
>
> Options:
> [a] Preserve all 4 (recommended if these are intentional).
> [b] Preserve some (I'll ask per rule).
> [c] Discard all 4 and use canonical only.
> [d] Abort.

For drifted canonical content (e.g. the user's `commitMessagePrefix`
for python deps is `fix(deps):` when the library template expects
`chore(deps):`), ask separately:

> Your python prod deps rule uses `commitMessagePrefix: "fix(deps):"`.
> For library repos the canonical prefix is `chore(deps):` (no release
> for library dep bumps) -- `fix(deps):` would trigger a patch release.
> This is the iac pattern. [a] Rewrite to `chore(deps):` (library
> canonical). [b] Leave as `fix(deps):` (the repo may have been
> miscategorized as library). [c] Abort.

For critical drift (node/iac `automergeStrategy: squash`):

> **Critical:** your node/iac config has `automergeStrategy: squash`.
> Squash drops the `[skip ci]` marker semantic-release emits on the
> dev->main promotion merge, which breaks the release cycle. The
> canonical value is `merge`. [a] Rewrite to `merge` (strongly
> recommended). [b] Leave as squash and accept the broken release cycle
> (not recommended). [c] Abort.

### Step 5 -- write the merged file

Only after every question is answered, call the generator via the
stable wrapper:

```bash
uv run ai-tools standardize <path> --area renovate
```

The Python generator produces the canonical content. For user-approved
custom content, you (the AI) re-insert it into the generated file via
`Read` + `Edit` after the generator runs.

The generator handles the deterministic pieces: template selection
(library vs iac), python-to-node string substitution (`pep621` ->
`npm`, `project.dependencies` -> `dependencies`, etc.), node/iac
`automergeStrategy: merge` enforcement, and cross-validation of commit
prefixes against `commit-scheme.json`.

### Step 6 -- verify

Re-run `Read` on `renovate.json5` and confirm:

- Canonical packageRules are present with canonical config
- Preserved-custom rules are present
- `automergeStrategy` is `merge` for node/iac (non-negotiable)
- Commit prefixes align with `commit-scheme.json`

Report the count of canonical rules written, custom rules preserved,
and the final `automergeStrategy` value for node/iac repos.

## Constraints

- **Zero writes before every question is answered.**
- **node/iac `automergeStrategy: merge` is non-negotiable.** If the user
  picks "leave as squash", emit a loud warning but still preserve their
  choice. Do NOT silently rewrite.
- **Commit prefix cross-validation.** The Python generator rejects
  writes if `commit-scheme.json` alignment fails. Surface that error to
  the user and offer to fix.
- **`library-template.json5` and `iac-template.json5`** are in the
  `ai-standardize-repo` skill directory, not in this one. That is
  intentional -- they are shared between this skill and the umbrella.
