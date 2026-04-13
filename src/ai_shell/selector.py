"""Interactive terminal multi-select widget using curses."""

from __future__ import annotations

import curses
import sys
from dataclasses import dataclass

import click

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
    """Show a curses multi-select menu and return chosen items.

    Raises ``click.ClickException`` when stdin is not a TTY.
    Returns an empty list if the user cancels (q / Ctrl-C).
    """
    if not sys.stdin.isatty():
        raise click.ClickException("--multi requires an interactive terminal (TTY).")

    selected_indices = curses.wrapper(_curses_main, items, title, max_selections)
    return [items[i] for i in sorted(selected_indices)]


def _curses_main(
    stdscr: curses.window,
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
    stdscr: curses.window,
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
