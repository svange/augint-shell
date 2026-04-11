---
name: ai-standardize-dotfiles
description: Detect-and-ask before writing `.editorconfig` and `.gitignore` from the canonical templates. Surfaces custom entries via AskUserQuestion before any overwrite so repo-specific patterns (language overrides, extra ignores) are preserved.
argument-hint: "[<repo path>]"
---

Standardize project config dotfiles at $ARGUMENTS (defaults to cwd).

## Core principle: ask before acting

The canonical `.editorconfig` and `.gitignore` templates cover the
common cases, but every repo has legitimate repo-specific additions
(language-specific editorconfig overrides, project-specific gitignore
entries, generated data paths, etc.). Never silently overwrite them.
Detect, classify, ask via `AskUserQuestion`, then write. If the user
aborts, exit with `Standardization aborted by user. No files were
modified.`

## Process

### Step 1 -- detect ecosystem

```bash
uv run ai-tools standardize <path> --verify --json
```

The drift report includes the detected language (python/node).
Multiple ecosystems are allowed -- check both sets.

### Step 2 -- read existing dotfiles (if present)

- `Read <repo>/.editorconfig`
- `Read <repo>/.gitignore`

If either is absent, skip that file's ask-loop and note it for Step 4
as "missing, will scaffold".

### Step 3 -- diff against canonical and classify

Parse each file and categorize every entry into three groups:

1. **Canonical entries that match** -- no action.
2. **Canonical entries that drifted** (e.g. python `indent_size = 2` in
   `.editorconfig` when canonical is `4`) -- plan to rewrite.
3. **Custom entries** -- authored by the user, not in the canonical
   template.

**`.editorconfig` custom content to detect:**

- Custom file-type sections (`[*.rs]`, `[*.go]`, etc.) that aren't in
  the canonical template
- Custom `indent_style` / `indent_size` overrides for specific paths
- Custom `max_line_length` overrides (the canonical template doesn't
  set this; user may have added one)
- Custom `charset` overrides

**`.gitignore` custom content to detect:**

- Entries beyond the canonical set. Canonical includes common python /
  node artifacts (`__pycache__/`, `*.pyc`, `dist/`, `build/`,
  `.coverage`, `htmlcov/`, `node_modules/`, `.env`, `.env.*`, `*.pem`,
  `*.key`, `.claude/settings.local.json`, `.ai-shell.toml`, etc.)
- Repo-specific generated data paths (e.g. `local-data/`, `fixtures/generated/`)
- Project-specific build outputs (e.g. `public/`, `out/`)
- Language-specific patterns the canonical template doesn't cover
  (e.g. Rust `target/`, Go `vendor/`)

**Anti-patterns to flag** (present when they shouldn't be):

- `uv.lock`, `package-lock.json`, or similar lock files in `.gitignore`
  -- lock files MUST be committed
- `tests/` in `.gitignore` -- test code must be tracked

### Step 4 -- ask before acting

> Your existing `.editorconfig` has 2 custom sections beyond the
> canonical template:
>
> 1. `[*.rs]` with `indent_size = 4` (Rust files)
> 2. `[Makefile]` with `indent_style = tab` (required for Makefiles)
>
> Options:
> [a] Preserve both (recommended).
> [b] Preserve some.
> [c] Discard and use canonical only.
> [d] Abort.

> Your existing `.gitignore` has 5 custom entries beyond the canonical
> template:
>
> 1. `local-data/` -- looks like a generated data path
> 2. `*.tfstate*` -- Terraform state files
> 3. `.venv-*/` -- multiple virtualenv directories (canonical only
>    includes `.venv/`)
> 4. `temp/` -- temporary scratch directory
> 5. `site/` -- mkdocs build output
>
> Options:
> [a] Preserve all 5 (recommended).
> [b] Preserve some.
> [c] Discard and use canonical only.
> [d] Abort.

**Anti-pattern flagging** -- if the existing `.gitignore` contains
`uv.lock` or similar, ALWAYS flag it:
> **Warning:** your `.gitignore` has `uv.lock` -- this is almost
> certainly wrong. Lock files must be committed so CI and contributors
> reproduce the same dependency graph. [a] Remove `uv.lock` from
> .gitignore (recommended). [b] Leave it (you are intentionally
> abandoning reproducibility). [c] Abort.

### Step 5 -- write the merged file

Only after every question is answered, write each file using the
canonical templates as the base and appending / preserving user-
approved custom entries at the end.

- `.editorconfig`: `Write` the canonical template, then `Edit` to
  append preserved custom sections
- `.gitignore`: `Write` the canonical template, then `Edit` to append
  preserved custom entries under a clearly-labeled comment like `#
  Custom (preserved from previous version)`

### Step 6 -- verify

Re-run `Read` on each written file and confirm:

- Canonical entries are present
- Preserved-custom entries are present
- Anti-patterns the user agreed to remove are gone

Report counts: canonical entries, custom entries preserved, custom
entries discarded, anti-patterns removed.

## Constraints

- **Zero writes before every question is answered.**
- **Lock files in .gitignore are always wrong.** Always flag them.
- **Safety patterns are non-negotiable.** `.env`, `.env.*`, `*.pem`,
  `*.key`, `.claude/settings.local.json`, `.ai-shell.toml` must be in
  `.gitignore`. If any are missing, add them without asking (with a
  note in the report) -- this is a security floor.
- **Multi-ecosystem support.** A repo with both `pyproject.toml` and
  `package.json` gets both python and node gitignore sections merged.
