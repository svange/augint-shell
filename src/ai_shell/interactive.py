"""Interactive multi-pane wizard for ``ai-shell claude --multi -i``.

Walks the user through a guided menu to configure each tmux pane,
then converts the collected choices into :class:`~ai_shell.tmux.PaneSpec`
objects ready for :func:`~ai_shell.tmux.build_tmux_commands`.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import click
from rich.console import Console

if TYPE_CHECKING:
    from ai_shell.tmux import PaneSpec


# ── Data model ───────────────────────────────────────────────────────


class PaneType(enum.Enum):
    """Types of panes available in interactive mode."""

    THIS_PROJECT = "this_project"
    BASH = "bash"
    WORKSPACE_REPO = "workspace_repo"


@dataclass
class PaneChoice:
    """A user's selection for a single window."""

    pane_type: PaneType
    repo_name: str = ""
    repo_path: str = ""


@dataclass
class InteractiveConfig:
    """Collected results from the interactive wizard."""

    pane_choices: list[PaneChoice] = field(default_factory=list)
    team_mode: bool = False
    shared_chrome: bool = False


# ── Option builder ───────────────────────────────────────────────────


@dataclass
class _PaneOption:
    """A single numbered option in the per-window menu."""

    label: str
    pane_type: PaneType
    repo_name: str = ""
    repo_path: str = ""


def _build_pane_options(
    project_name: str,
    workspace_repos: list[dict[str, Any]] | None,
) -> list[_PaneOption]:
    """Build the numbered option list for per-window type selection."""
    options: list[_PaneOption] = [
        _PaneOption(
            label=f"This project ({project_name}) - Claude in worktree",
            pane_type=PaneType.THIS_PROJECT,
        ),
        _PaneOption(
            label="Bash shell",
            pane_type=PaneType.BASH,
        ),
    ]
    if workspace_repos:
        for repo in workspace_repos:
            name = repo["name"]
            path = repo.get("path", f"./{name}")
            repo_type = repo.get("repo_type", "")
            label = f"{name} ({repo_type})" if repo_type else name
            options.append(
                _PaneOption(
                    label=label,
                    pane_type=PaneType.WORKSPACE_REPO,
                    repo_name=name,
                    repo_path=path,
                )
            )
    return options


# ── Wizard ───────────────────────────────────────────────────────────


def run_interactive_wizard(
    *,
    project_name: str,
    workspace_repos: list[dict[str, Any]] | None = None,
    console: Console | None = None,
) -> InteractiveConfig | None:
    """Walk the user through the interactive multi-pane setup.

    Returns :class:`InteractiveConfig` with all choices, or ``None`` if the
    user cancels (Ctrl-C / EOFError).
    """
    if console is None:
        console = Console(stderr=True)

    options = _build_pane_options(project_name, workspace_repos)

    try:
        # Step 1: number of windows
        num_windows: int = click.prompt(
            "How many windows?",
            type=click.IntRange(2, 4),
            default=2,
        )

        # Step 2: per-window type
        choices: list[PaneChoice] = []
        for win_idx in range(1, num_windows + 1):
            console.print()
            console.print(f"  [bold]Window {win_idx}:[/bold]")
            for i, opt in enumerate(options, 1):
                console.print(f"    {i}. {opt.label}")

            selection: int = click.prompt(
                f"  Select type for window {win_idx}",
                type=click.IntRange(1, len(options)),
                default=1,
            )
            chosen = options[selection - 1]
            choices.append(
                PaneChoice(
                    pane_type=chosen.pane_type,
                    repo_name=chosen.repo_name,
                    repo_path=chosen.repo_path,
                )
            )

        # Step 3: pre-launch options
        console.print()
        team_mode = click.confirm(
            "Enable teams mode on the primary Claude pane?",
            default=False,
        )
        shared_chrome = click.confirm(
            "Enable shared Chrome browser for all Claude panes?",
            default=False,
        )

    except (EOFError, KeyboardInterrupt, click.Abort):
        return None

    return InteractiveConfig(
        pane_choices=choices,
        team_mode=team_mode,
        shared_chrome=shared_chrome,
    )


# ── Pane builder ─────────────────────────────────────────────────────


def build_interactive_panes(
    *,
    config: InteractiveConfig,
    project_name: str,
    container_name: str,
    container_project_root: str,
    safe: bool,
    extra_args: tuple[str, ...],
    mcp_config_path: str | None = None,
    setup_worktree_fn: Callable[[str, str, str], str],
) -> list[PaneSpec]:
    """Convert :class:`InteractiveConfig` into pane specs for tmux.

    Parameters
    ----------
    setup_worktree_fn
        ``(container_name, project_dir, worktree_name) -> worktree_abs_path``.
        In production this is ``tools._setup_worktree``; in tests, a mock.
    """
    from ai_shell.tmux import PaneSpec, build_claude_pane_command

    panes: list[PaneSpec] = []
    team_assigned = False
    bash_counter = 0

    for choice in config.pane_choices:
        if choice.pane_type == PaneType.THIS_PROJECT:
            wt_name = uuid.uuid4().hex[:8]
            worktree_dir = setup_worktree_fn(container_name, container_project_root, wt_name)
            use_team = config.team_mode and not team_assigned
            pane_cmd = build_claude_pane_command(
                repo_name=project_name,
                safe=safe,
                extra_args=extra_args,
                worktree_name=wt_name,
                mcp_config_path=mcp_config_path if config.shared_chrome else None,
                team_env=use_team,
            )
            if use_team:
                team_assigned = True
            panes.append(
                PaneSpec(
                    name=f"{project_name}-wt-{wt_name}",
                    command=pane_cmd,
                    working_dir=worktree_dir,
                )
            )

        elif choice.pane_type == PaneType.BASH:
            bash_counter += 1
            panes.append(
                PaneSpec(
                    name=f"bash-{bash_counter}",
                    command="/bin/bash",
                    working_dir=container_project_root,
                )
            )

        elif choice.pane_type == PaneType.WORKSPACE_REPO:
            rel = choice.repo_path.lstrip("./")
            working_dir = f"{container_project_root}/{rel}"
            use_team = config.team_mode and not team_assigned
            pane_cmd = build_claude_pane_command(
                repo_name=choice.repo_name,
                safe=safe,
                extra_args=extra_args,
                mcp_config_path=mcp_config_path if config.shared_chrome else None,
                team_env=use_team,
            )
            if use_team:
                team_assigned = True
            panes.append(
                PaneSpec(
                    name=choice.repo_name,
                    command=pane_cmd,
                    working_dir=working_dir,
                )
            )

    return panes
