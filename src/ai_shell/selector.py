"""Interactive terminal multi-select widget.

Uses curses on Unix/WSL.  Falls back to a Rich numbered-prompt selector on
Windows or anywhere ``_curses`` is unavailable.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    import curses as _curses_mod

try:
    import curses

    _CURSES_AVAILABLE = True
except ImportError:
    curses = None  # type: ignore[assignment]
    _CURSES_AVAILABLE = False

MAX_SELECTIONS = 4


@dataclass
class SelectionItem:
    """An item in the multi-select menu."""

    label: str
    value: str  # e.g. repo path relative to CWD ("./woxom-crm") or "."
    description: str = ""


def interactive_multi_select(
    items: list[SelectionItem],
    *,
    title: str = "Select repos (up to 4)",
    max_selections: int = MAX_SELECTIONS,
) -> list[SelectionItem]:
    """Show a multi-select menu and return chosen items.

    Uses curses when available (Linux/macOS/WSL), otherwise falls back to a
    Rich numbered-prompt selector (Windows).

    Raises ``click.ClickException`` when stdin is not a TTY.
    Returns an empty list if the user cancels (q / Ctrl-C).
    """
    if not sys.stdin.isatty():
        raise click.ClickException("--multi requires an interactive terminal (TTY).")

    if _CURSES_AVAILABLE:
        selected_indices = curses.wrapper(_curses_main, items, title, max_selections)
        return [items[i] for i in sorted(selected_indices)]

    return _rich_multi_select(items, title=title, max_selections=max_selections)


# ── Rich fallback (Windows) ───────────────────────────────────────────


def _rich_multi_select(
    items: list[SelectionItem],
    *,
    title: str,
    max_selections: int,
) -> list[SelectionItem]:
    """Numbered-prompt selector using Rich.  Works on all platforms."""
    from rich.console import Console

    console = Console()
    console.print()
    console.print(f"  [bold]{title}[/bold]")
    console.print()
    for i, item in enumerate(items, 1):
        desc = f"  [dim]({item.description})[/dim]" if item.description else ""
        console.print(f"    {i}. {item.label}{desc}")
    console.print()

    while True:
        try:
            raw = console.input(
                f"  [dim]Enter numbers separated by commas (max {max_selections}), "
                "or 'q' to cancel:[/dim] "
            )
        except (EOFError, KeyboardInterrupt):
            return []

        raw = raw.strip()
        if not raw or raw.lower() == "q":
            return []

        parts = [p.strip() for p in raw.split(",") if p.strip()]
        indices: list[int] = []
        valid = True
        for part in parts:
            if not part.isdigit():
                console.print(f"  [red]'{part}' is not a number.[/red]")
                valid = False
                break
            num = int(part)
            if num < 1 or num > len(items):
                console.print(f"  [red]{num} is out of range (1-{len(items)}).[/red]")
                valid = False
                break
            idx = num - 1
            if idx not in indices:
                indices.append(idx)

        if not valid:
            continue
        if len(indices) > max_selections:
            console.print(f"  [red]Max {max_selections} selections.[/red]")
            continue
        if not indices:
            continue

        return [items[i] for i in sorted(indices)]


# ── Curses interactive selector (Unix/WSL) ─────────────────────────────


def _curses_main(
    stdscr: _curses_mod.window,
    items: list[SelectionItem],
    title: str,
    max_selections: int,
) -> set[int]:
    """Curses inner loop.  Returns set of selected indices."""
    curses.curs_set(0)  # hide cursor
    stdscr.clear()

    cursor = 0
    selected: set[int] = set()
    flash_msg = ""
    flash_countdown = 0

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        # Title
        _safe_addstr(stdscr, 0, 2, title, curses.A_BOLD, w)

        # Items
        for i, item in enumerate(items):
            y = i + 2
            if y >= h - 2:
                break

            check = "[x]" if i in selected else "[ ]"
            pointer = ">" if i == cursor else " "
            line = f"  {pointer} {check} {item.label}"
            if item.description:
                line += f"  ({item.description})"

            attr = curses.A_REVERSE if i == cursor else 0
            if i in selected and i != cursor:
                attr = curses.A_BOLD
            _safe_addstr(stdscr, y, 0, line, attr, w)

        # Status line
        status_y = min(len(items) + 3, h - 2)
        status = f"  {len(selected)}/{max_selections} selected"
        _safe_addstr(stdscr, status_y, 0, status, 0, w)

        # Help line
        help_text = "  space=toggle  enter=confirm  q=cancel"
        _safe_addstr(stdscr, status_y + 1, 0, help_text, curses.A_DIM, w)

        # Flash message (e.g. "Max selections reached")
        if flash_countdown > 0:
            _safe_addstr(stdscr, status_y + 2, 2, flash_msg, curses.A_BOLD, w)
            flash_countdown -= 1

        stdscr.refresh()

        key = stdscr.getch()

        if key == curses.KEY_UP and cursor > 0:
            cursor -= 1
        elif key == curses.KEY_DOWN and cursor < len(items) - 1:
            cursor += 1
        elif key == ord(" "):
            if cursor in selected:
                selected.discard(cursor)
            elif len(selected) < max_selections:
                selected.add(cursor)
            else:
                flash_msg = f"Max {max_selections} selections"
                flash_countdown = 3
        elif key in (curses.KEY_ENTER, 10, 13):
            return selected
        elif key in (ord("q"), ord("Q"), 27, 3):  # q, Q, Esc, Ctrl-C
            return set()

    return selected  # unreachable, satisfies type checker


def _safe_addstr(
    stdscr: _curses_mod.window,
    y: int,
    x: int,
    text: str,
    attr: int,
    max_width: int,
) -> None:
    """Write text to curses window, truncating to fit and ignoring overflow errors."""
    h, _ = stdscr.getmaxyx()
    if y >= h or y < 0:
        return
    truncated = text[: max_width - x - 1] if len(text) + x >= max_width else text
    try:
        stdscr.addstr(y, x, truncated, attr)
    except curses.error:
        pass  # writing to bottom-right corner raises in some terminals
