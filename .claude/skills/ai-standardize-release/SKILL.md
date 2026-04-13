---
name: ai-standardize-release
description: Detect-and-ask before writing the canonical semantic-release config (pyproject.toml [tool.semantic_release] for python, .releaserc.json for node). Surfaces custom branches, build_command, commit_parser, and changelog overrides via AskUserQuestion before any overwrite.
argument-hint: "[<repo path>]"
---

Standardize the semantic-release config at $ARGUMENTS (defaults to cwd).

## Core principle: ask before acting

`tomlkit` merge preserves content OUTSIDE `[tool.semantic_release]` in
pyproject.toml, but custom fields WITHIN the section are overwritten by
the canonical generator. The user may have intentional customizations
(custom `branches`, `build_command` tweaks, additional
`exclude_commit_patterns`) that must be preserved. Detect them and ask
before writing. If the user aborts, exit with `Standardization aborted
by user. No files were modified.`

## Process

### Step 1 -- detect language and repo type

```bash
uv run ai-tools standardize <path> --verify --json
```

The drift report includes python/node and library/service. On ambiguous,
ask and stop.

### Step 2 -- read the existing config (if present)

- **Python path**: `Read <repo>/pyproject.toml` and locate
  `[tool.semantic_release]` and any subsections
  (`[tool.semantic_release.branches.*]`,
  `[tool.semantic_release.changelog]`, etc.) via TOML parsing (never
  string grep -- the detection section of the plan explicitly rejects
  that).
- **Node path**: `Read <repo>/.releaserc.json` (or the `release` key in
  `package.json` if it's a legacy layout).

If absent, skip to Step 4 with one question:
> No existing semantic-release config. Scaffold the canonical template
> for `<language>/<type>`? [a] Yes. [b] Abort.

### Step 3 -- diff against canonical and classify

Parse the existing config and categorize every field into three
groups:

1. **Canonical fields that match** -- no action.
2. **Canonical fields that drifted** -- plan to rewrite.
3. **Custom fields** -- authored by the user, not in the canonical
   template.

**Python custom content to detect:**

- Custom `branches` entries beyond `main` (library) or `main`+`dev`
  (service)
- Custom `build_command` -- the canonical is `uv lock && uv build` for
  libraries, `""` for service
- Custom `commit_parser` / `commit_parser_options` (especially
  `patch_tags` additions)
- Custom `exclude_commit_patterns` entries beyond the canonical set
- Custom `assets` (beyond `uv.lock`)
- Custom `version_variables` list entries
- Custom `[tool.semantic_release.changelog]` overrides

**Node custom content to detect:**

- Custom `branches` entries
- Custom `releaseRules` additions in `@semantic-release/commit-analyzer`
- Custom `plugins` beyond the canonical list (canonical includes
  `commit-analyzer`, `release-notes-generator`, `changelog`, `git`, and
  -- for node/library only -- `@semantic-release/npm`)
- Custom `tagFormat` (the canonical is `<short-name>-v${version}`)

### Step 4 -- ask before acting

> Your existing `pyproject.toml` `[tool.semantic_release]` section has
> 3 custom fields I'd overwrite:
>
> 1. `build_command = "uv lock && uv build && ./scripts/post-build.sh"`
>    -- adds a post-build script after the canonical `uv build`
> 2. `exclude_commit_patterns` includes an extra pattern
>    `'''release:\\(.+\\)'''` to exclude release commits
> 3. `[tool.semantic_release.branches.dev]` with
>    `prerelease_token = "rc"` (you have dev as a prerelease branch, the
>    library canonical is main-only)
>
> Options:
> [a] Preserve all 3 (recommended if these are intentional).
> [b] Preserve some (I'll ask per field).
> [c] Discard all 3 and use canonical only.
> [d] Abort.

For the branches case specifically, ask:
> You have a dev prerelease branch configured. The library canonical is
> main-only; dev prereleases are an service pattern. Is this repo actually
> service and the detection was wrong? [a] Yes, it's service -- re-run
> detection. [b] It's library but I want dev prereleases anyway
> (preserve). [c] Discard the dev branch entry and use canonical. [d]
> Abort.

### Step 5 -- write the merged file

Only after every question is answered, call the generator via the
stable wrapper:

```bash
uv run ai-tools standardize <path> --area release
```

The Python generator uses `tomlkit` for python merges so content
OUTSIDE `[tool.semantic_release]` is preserved automatically. For
user-approved custom content WITHIN the section, you (the AI) must
re-insert it via `Read` + `Edit` after the generator runs. The
generator writes canonical fields; preserving custom fields in the
canonical section is the skill's responsibility.

The generator also cross-validates the release exclude patterns against
`commit-scheme.json` to ensure Renovate prefixes and semantic-release
rules stay aligned. If the cross-validation fails, surface the error
and offer to fix the alignment.

### Step 6 -- verify

Re-run `Read` on the written file and confirm:

- All canonical fields are present with canonical values
- Preserved-custom fields are present with the user's values
- `commit-scheme.json` alignment passes
- `tag_format` is `<short-name>-v{version}` (python) or
  `<short-name>-v${version}` (node)
- `branches` matches the detected repo type (main-only library vs
  main+dev service)

Report the count of canonical fields written, custom fields preserved,
the tag format, and the branches configured.

## Constraints

- **Zero writes before every question is answered.**
- **TOML parsing, not string grep.** Detect existing config via
  `tomllib.load`. Legacy skill prose that greps for the string
  `semantic_release` in pyproject.toml was removed in round 2 -- never
  reintroduce it.
- **Commit prefix cross-validation** with `commit-scheme.json` is
  non-negotiable. Surface alignment failures to the user; do not
  silently skip them.
- **Library vs service branches.** Library is main-only; service is main+dev.
  If the existing config disagrees with detection, surface it as a
  question (it may indicate a detection error).
