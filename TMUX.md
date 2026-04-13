# TMUX Multi-Pane Claude Design

## Problem

Working on a workspace with multiple child repos requires switching between repos
one at a time. There's no way to run Claude Code in parallel across repos.

## Solution

`ai-shell claude --multi` launches an interactive repo picker, creates a single
dev container with all selected repos mounted, and runs tmux inside that container
with Claude Code in each pane (up to 4).

## Architecture

```
HOST                                    DOCKER CONTAINER
                                        (augint-shell-{workspace}-multi)
ai-shell claude --multi
  |
  +--> parse workspace.yaml             /root/projects/workspace-root/
  +--> curses selector (host TTY)       /root/projects/woxom-crm/
  +--> create multi container --------> /root/projects/woxom-infra/
  +--> docker exec: tmux setup          /root/projects/woxom-common/
  +--> docker exec -it: tmux attach
                                        tmux session "claude-multi"
                                        +------------------+------------------+
                                        | pane 0: woxom-crm | pane 1: infra   |
                                        | claude -c         | claude -c       |
                                        +------------------+------------------+
                                        | pane 2: common   |                  |
                                        | claude -c         |                  |
                                        +------------------+------------------+
```

### Why inside the container, not on the host

- We own the Dockerfile; tmux is already installed (line 189)
- One container = one UV cache, one filesystem. No cross-container venv corruption.
- The Docker image is published to DockerHub via pipeline -- any additions propagate automatically
- Claude Code, git, gh, aws-cli, uv, npm, node, and all dev tools are already in the image
- The user doesn't need tmux installed on the host (WSL2)

### What runs where

| Step | Where | Tool |
|------|-------|------|
| Parse workspace.yaml | Host | pyyaml (existing dep) |
| Interactive repo selector | Host | curses (stdlib) |
| Create/find multi container | Host | Docker SDK (existing dep) |
| tmux session setup | Container | docker exec -> tmux |
| tmux attach (final) | Container | docker exec -it -> tmux attach |
| Claude Code instances | Container | claude binary (in image) |

## Detailed flow

### 1. Host: workspace discovery and selection

Parse `workspace.yaml` from CWD. Build menu items: workspace root + each child
repo. Show curses-based multi-select (arrow keys, space to toggle, enter to
confirm). Max 4 selections.

### 2. Host: container lifecycle

Create or reuse a "multi" dev container. Named `augint-shell-{workspace}-multi`.

**Mounts** -- same as a regular dev container, but with MULTIPLE project directories:

```python
# Required: mount each selected repo
for repo in selected_repos:
    mounts.append(Mount(
        target=f"/root/projects/{repo['name']}",
        source=str(repo_dir.resolve()),
        type="bind",
        read_only=False,
        consistency="delegated",
    ))

# Also mount the workspace root (for workspace.yaml, CLAUDE.md, etc.)
mounts.append(Mount(
    target=f"/root/projects/{workspace_name}",
    source=str(workspace_dir.resolve()),
    type="bind",
    read_only=False,
    consistency="delegated",
))

# Standard optional mounts (same as single dev container):
# ~/.claude, ~/.claude.json, ~/.aws, ~/.ssh (ro), ~/.gitconfig (ro),
# ~/projects/CLAUDE.md (ro), /var/run/docker.sock (ro), UV cache volume
```

**Environment** -- same as `build_dev_environment()` plus:

```python
# Unset the global UV_PROJECT_ENVIRONMENT.
# The Dockerfile sets it to /root/.cache/uv/venvs/project (a single
# shared path). With multiple repos in one container, each pane sets
# its own UV_PROJECT_ENVIRONMENT before running claude, so the global
# must not override them.
env["UV_PROJECT_ENVIRONMENT"] = ""
```

**Working directory**: `/root/projects/{workspace_name}` (workspace root).

**Entrypoint**: runs normally (`docker-entrypoint.sh`):
- Copies/fixes gitconfig
- Sets up GH_TOKEN git credential helper
- Prunes stale worktrees
- Runs `uv sync` if workspace root has `uv.lock`
- Falls through to `tail -f /dev/null`

### 3. Container: tmux session setup

All tmux commands run via `docker exec <container> tmux ...`

**Create session and panes:**

```bash
# Create session with first pane
tmux new-session -d -s claude-multi -c /root/projects/{repo0}

# Additional panes (one per additional repo)
tmux split-window -t claude-multi:0 -c /root/projects/{repo1}
tmux split-window -t claude-multi:0 -c /root/projects/{repo2}  # if 3+
tmux split-window -t claude-multi:0 -c /root/projects/{repo3}  # if 4

# Apply layout
tmux select-layout -t claude-multi:0 {layout}
```

**Layouts:**

| Panes | Layout | tmux name | Visual |
|-------|--------|-----------|--------|
| 2 | Horizontal split | `even-vertical` | top / bottom |
| 3 | 1 top, 2 bottom | `main-horizontal` | top pane ~65%, two smaller bottom |
| 4 | Even quarters | `tiled` | 2x2 grid |

**Set pane titles:**

```bash
tmux select-pane -t claude-multi:0.0 -T "woxom-crm"
tmux select-pane -t claude-multi:0.1 -T "woxom-infra"
# ...
```

**Send commands to each pane:**

Each pane gets a per-project UV venv path and runs claude with retry logic.
Tries `-c` (continue previous conversation) first; falls back to a fresh
session if no prior conversation exists:

```bash
tmux send-keys -t claude-multi:0.0 \
  'export UV_PROJECT_ENVIRONMENT=/root/.cache/uv/venvs/woxom-crm; claude --dangerously-skip-permissions -c -n woxom-crm || claude --dangerously-skip-permissions -n woxom-crm' \
  Enter
```

For `--safe` mode (no retry, no permissive flags):

```bash
tmux send-keys -t claude-multi:0.0 \
  'UV_PROJECT_ENVIRONMENT=/root/.cache/uv/venvs/woxom-crm claude -n woxom-crm' \
  Enter
```

### 4. Container: tmux configuration

Applied via `docker exec <container> tmux set-option ...` after session creation.

```
# ── Mouse & responsiveness ─────────────────────────────────────────
# Click to select pane, drag to resize, scroll within pane.
set-option -t claude-multi mouse on
# Near-zero escape delay so Claude Code's TUI responds instantly.
set-option -t claude-multi escape-time 10
# Generous scrollback buffer.
set-option -t claude-multi history-limit 50000
# Claude Code detects focus gain/loss for auto-refresh.
set-option -t claude-multi focus-events on

# ── Pane borders: amber active, dusty mauve inactive ─────────────
# Warm colour scheme designed to complement Claude Code's warm UI:
#   colour172 (#d78700) = amber   -> active pane (unmistakable "you are here")
#   colour95  (#875f5f) = mauve   -> inactive panes (visible, won't blend w/ gray)
# Three distinct visual bands: amber=active, mauve=inactive, gray=Claude Code UI.
set-option -t claude-multi pane-border-status top
set-option -t claude-multi pane-border-lines heavy
set-option -t claude-multi pane-border-format \
  "#{?pane_active,#[fg=colour172 bold] #{pane_title} ,#[fg=colour95] #{pane_title} }"
set-option -t claude-multi pane-border-style "fg=colour95"
set-option -t claude-multi pane-active-border-style "fg=colour172,bold"
# Arrow indicators on the active pane border.
set-option -t claude-multi pane-border-indicators arrows

# ── Status bar ─────────────────────────────────────────────────────
# Session name in amber (matches active border), help hints in mauve.
set-option -t claude-multi status-style "bg=colour235 fg=colour248"
set-option -t claude-multi status-left "#[fg=colour172,bold] #S #[fg=colour248]| "
set-option -t claude-multi status-right "#[fg=colour95] C-b z=zoom  C-b d=detach "
set-option -t claude-multi status-left-length 40
set-option -t claude-multi status-right-length 40

# ── Terminal (server-level) ────────────────────────────────────────
# True color support for Claude Code's syntax highlighting.
set-option -s default-terminal "tmux-256color"
set-option -sa terminal-overrides ",xterm*:Tc"
```

### 5. Host: attach

The final command replaces the host process:

```python
os.execvp("docker", [
    "docker", "exec", "-it", container_name,
    "tmux", "attach-session", "-t", "claude-multi",
])
```

The user is now inside the tmux session. They can:
- Click panes to switch focus
- Drag pane borders to resize
- Scroll with mouse wheel in the focused pane
- Use `Ctrl-b z` to zoom/unzoom a single pane (fullscreen toggle)
- Use `Ctrl-b arrow` to move between panes via keyboard
- Use `Ctrl-b d` to detach (container stays running, re-attach later)

**Important**: Use `Ctrl-b d` to detach, NOT `Ctrl-d`. `Ctrl-d` sends EOF to
the active pane's shell and may close the terminal window without properly
detaching. The tmux session and all Claude instances continue running in the
container either way.

### 6. Host: reconnect to existing session

Running `ai-shell claude --multi` again checks for an existing tmux session
in the container before showing the repo selector. If found, it prompts:

```
Found existing tmux session 'claude-multi-my-workspace'.
  Reconnect, start fresh, or cancel? [reconnect]:
```

- **reconnect** (default): immediately re-attaches to the running session
- **fresh**: kills the old session and shows the repo selector to start over
- **cancel**: exits without doing anything

## Dependency isolation

### Python venv isolation

The Dockerfile sets `UV_PROJECT_ENVIRONMENT=/root/.cache/uv/venvs/project`
globally. Without per-pane overrides, all projects would share one venv.

**How it works:**

1. Each tmux pane **exports** a per-project path before running claude:
   ```
   export UV_PROJECT_ENVIRONMENT=/root/.cache/uv/venvs/{project_name}
   ```
2. Each pane runs `uv sync` (if `pyproject.toml` exists) to initialise the
   per-repo venv before Claude starts.
3. Claude Code and all subprocesses it spawns (pre-commit, pytest, uv run)
   inherit the pane's environment, so each project uses its own venv.

The UV **download cache** (`/root/.cache/uv/` excluding venvs) is safely shared --
uv uses file locks for concurrent access.

### Node.js npm isolation

Each pane also runs `npm ci` (or `npm install`) when `package-lock.json`
(or `package.json`) is detected. The npm download cache is stored in a shared
Docker named volume (`augint-shell-npm-cache` at `/root/.npm`), so packages
are not re-downloaded across containers.

### Per-pane startup command

The full pane startup sequence (non-safe mode):

```bash
export UV_PROJECT_ENVIRONMENT=/root/.cache/uv/venvs/{repo_name}; \
  if [ -f pyproject.toml ]; then uv sync 2>&1 | tail -3; fi; \
  if [ -f package-lock.json ]; then npm ci --loglevel=warn 2>&1 | tail -3; \
  elif [ -f package.json ]; then npm install --loglevel=warn 2>&1 | tail -3; fi; \
  claude --dangerously-skip-permissions -c -n {repo} || \
  claude --dangerously-skip-permissions -n {repo}
```

## Worktree support

`--multi --worktree <name>` creates a git worktree for each selected repo, so
agents work on branches (`worktree-<name>`) rather than directly on the default
branch.

- Worktrees are placed at `.claude/worktrees/<name>/` inside each repo
- Each worktree gets its own venv at `/root/.cache/uv/venvs/{repo}-wt-{name}`
- Agents can make changes without affecting each other's working state
- When `--worktree` is given without a value, a random name is generated

## Agent Teams mode (`--team`)

`ai-shell claude --team` launches Claude Code with the experimental Agent Teams
feature enabled (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`).

Unlike `--multi` (which creates independent Claude instances, each in its own
tmux pane), `--team` launches a single Claude instance that acts as team lead.
Agent Teams manages its own tmux pane splitting for teammates.

When `workspace.yaml` is present, the lead agent receives workspace context
(repo names, types, and container paths) and can spawn teammates for each repo.

**Key differences from `--multi`:**

| | `--multi` | `--team` |
|------|-----------|----------|
| Agents | Independent, no communication | Coordinated via lead + messaging |
| tmux | Our custom session | Agent Teams manages its own |
| Directory control | Deterministic (per-pane working dir) | Natural-language (lead tells teammates) |
| Stability | Stable | Experimental |

`--team` and `--multi` are mutually exclusive (both manage tmux differently).

## Files to create/modify

### New files

| File | Purpose |
|------|---------|
| `src/ai_shell/selector.py` | Curses-based interactive multi-select widget |
| `src/ai_shell/tmux.py` | Pure-function tmux command builder (returns command lists, no subprocess calls) |
| `tests/unit/test_multi.py` | Tests for selector, tmux builder, and CLI integration |

### Modified files

| File | Change |
|------|--------|
| `src/ai_shell/defaults.py` | Add `project_name` param to `build_dev_environment()`, set `UV_PROJECT_ENVIRONMENT` per-project |
| `src/ai_shell/container.py` | Add `ensure_multi_container()` and `build_multi_mounts()` methods |
| `src/ai_shell/cli/commands/tools.py` | Add `--multi` flag to `claude` command, add `_launch_multi()` orchestrator |
| `tests/unit/test_defaults.py` | Test `UV_PROJECT_ENVIRONMENT` is set per-project |
| `tests/unit/test_cli_tools.py` | Update mocks for new `project_name` kwarg; add `--multi` tests |

### No Dockerfile changes needed

tmux (line 189), fzf (line 190), and all other tools are already installed.

### No new dependencies

- `curses` -- stdlib (available on all Linux/WSL Python)
- `pyyaml` -- already a runtime dependency
- `shlex` -- stdlib

## Module designs

### `src/ai_shell/selector.py`

```python
@dataclass
class SelectionItem:
    label: str          # Display name
    value: str          # Relative path (e.g. "./woxom-crm" or ".")
    description: str    # Optional subtitle (e.g. "service" or "workspace root")

def interactive_multi_select(
    items: list[SelectionItem],
    *,
    title: str = "Select repos",
    max_selections: int = 4,
) -> list[SelectionItem]:
    """Curses multi-select. Returns empty list on cancel."""
```

UI:
```
  ai-shell claude --multi

  > [x] woxom-ecosystem (workspace root)
    [ ] woxom-infra
    [x] woxom-common
    [ ] woxom-crm

  2/4 selected | space=toggle  enter=confirm  q=cancel
```

Uses `curses.wrapper()` for robust terminal restoration.

### `src/ai_shell/tmux.py`

Pure functions -- return command arg lists, never call subprocess.

```python
@dataclass
class PaneSpec:
    name: str           # Pane title (repo name)
    command: str        # Full shell command for the pane
    working_dir: str    # Container path (e.g. /root/projects/woxom-crm)

def build_pane_command(
    *,
    project_name: str,
    safe: bool = False,
    extra_args: tuple[str, ...] = (),
) -> str:
    """Build the shell command for a tmux pane.

    Sets UV_PROJECT_ENVIRONMENT per-project, then runs claude with
    retry logic (try -c first, fall back to fresh if it fails).
    """

def select_layout(pane_count: int) -> str:
    """2=even-vertical, 3=main-horizontal, 4=tiled."""

def build_tmux_commands(
    container_name: str,
    session_name: str,
    panes: list[PaneSpec],
) -> list[list[str]]:
    """Build the full sequence of docker exec + tmux commands.

    Returns list of arg lists for subprocess.run().
    Last element is the 'docker exec -it tmux attach' command
    (caller should os.execvp it).
    """

TMUX_SESSION_OPTIONS: dict[str, str]  # The config from section 4 above
```

### `src/ai_shell/container.py` additions

```python
class ContainerManager:
    ...

    def ensure_multi_container(
        self,
        workspace_name: str,
        repo_dirs: dict[str, Path],   # {repo_name: host_path}
    ) -> str:
        """Create or reuse a multi-project dev container.

        Named augint-shell-{workspace_name}-multi.
        Mounts each repo at /root/projects/{name}.
        """

    def _build_multi_mounts(
        self,
        repo_dirs: dict[str, Path],
    ) -> list[Mount]:
        """Build mount list for a multi-project container.

        Same as build_dev_mounts but with N project directories.
        """
```

### `src/ai_shell/cli/commands/tools.py` additions

```python
@click.option(
    "--multi",
    "do_multi",
    is_flag=True,
    default=False,
    help="Launch Claude Code in multiple workspace repos via tmux.",
)
```

New helper:
```python
def _launch_multi(ctx, *, safe, use_aws, cli_profile, skip_preflight, extra_args):
    """Workspace multi-pane Claude launcher."""
    # 1. Validate: stdin is TTY, workspace.yaml exists
    # 2. Parse workspace.yaml with pyyaml
    # 3. Build SelectionItems: workspace root + each child repo
    # 4. interactive_multi_select()
    # 5. Validate selected repo dirs exist (error: run /ai-workspace-sync)
    # 6. If 1 selected: skip tmux, run claude for that repo directly
    # 7. Create/reuse multi container via ensure_multi_container()
    # 8. Build PaneSpecs with per-project UV_PROJECT_ENVIRONMENT
    # 9. Execute tmux setup commands via subprocess.run()
    # 10. os.execvp the final tmux attach command
```

Incompatibility: `--multi` + `--init/--update/--reset/--clean/--worktree` raises error.

## Flag propagation

| User flag | Effect in pane command |
|-----------|----------------------|
| (default) | `claude --dangerously-skip-permissions -c -n {repo} \|\| claude --dangerously-skip-permissions -n {repo}` |
| `--safe` | `claude -n {repo}` (no permissive flags, no retry) |
| `--aws` | Container env gets `CLAUDE_CODE_USE_BEDROCK=1` |
| `--profile X` | Container env gets `AWS_PROFILE=X` for bedrock |
| `-- --debug` | Appended to claude command in each pane |

## Edge cases

| Scenario | Behavior |
|----------|----------|
| No `workspace.yaml` | Error: "--multi requires a workspace repo (no workspace.yaml found)" |
| 0 selections | Print "No repos selected" and exit cleanly |
| 1 selection | Skip tmux, run claude directly for that repo |
| Repo dir doesn't exist | Error: "woxom-crm not found. Run /ai-workspace-sync first" |
| Existing tmux session in container | Prompt: reconnect / fresh / cancel |
| `--multi --init` | Error: "--multi is incompatible with --init/--update/--reset/--clean/--worktree" |
| stdin not a TTY | Error: "--multi requires an interactive terminal" |
| Container already running | Reuse it (same as single-project behavior) |
| Stale multi container with wrong mounts | Stop, remove, recreate with correct mounts |

## Test strategy

### Pure function tests (`test_multi.py`)

No mocking needed -- these are data-in, data-out:

- `test_select_layout_{2,3,4}` -- correct tmux layout name
- `test_build_pane_command_default` -- UV_PROJECT_ENVIRONMENT + claude retry logic
- `test_build_pane_command_safe` -- no permissive flags
- `test_build_pane_command_extra_args` -- args propagated after `--`
- `test_build_tmux_commands_{2,3,4}_panes` -- correct split count, layout, titles
- `test_build_tmux_commands_session_options` -- mouse, escape-time, etc. present
- `test_build_tmux_commands_container_prefix` -- all commands prefixed with `docker exec`

### Selector tests (`test_multi.py`)

- `test_selection_item_dataclass` -- construction
- `test_interactive_select_not_tty` -- raises when not a TTY

### CLI integration tests (`test_cli_tools.py`)

Mock `interactive_multi_select`, `subprocess.run`, `os.execvp`, `ContainerManager`:

- `test_claude_multi_no_workspace_yaml` -- error message
- `test_claude_multi_incompatible_with_init` -- error
- `test_claude_multi_incompatible_with_worktree` -- error
- `test_claude_multi_calls_selector` -- selector invoked with correct items
- `test_claude_multi_creates_container` -- `ensure_multi_container` called with correct repos
- `test_claude_multi_builds_tmux_session` -- tmux commands executed
- `test_claude_multi_single_selection_no_tmux` -- direct launch, no tmux
- `test_claude_multi_propagates_safe` -- `--safe` in pane commands
- `test_claude_multi_propagates_aws` -- bedrock env var in container

### Defaults tests (`test_defaults.py`)

- `test_build_dev_environment_sets_uv_project_env` -- per-project path
- `test_build_dev_environment_no_project_name_no_uv_env` -- backwards compat

## Verification checklist

1. `uv run pytest -v` -- all tests pass, no regressions
2. `uv run ruff check src/ tests/`
3. `uv run mypy src/`
4. `uv run pre-commit run --all-files`
5. Manual: `cd` to workspace, run `ai-shell claude --multi`, pick 2-3 repos,
   verify tmux opens with correct panes and Claude running in each
6. Manual: verify mouse clicks switch panes, scrolling works, `Ctrl-b z` zooms
7. Manual: verify `uv sync` in one pane doesn't corrupt another pane's venv
