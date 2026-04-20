"""Capture stdin keystrokes during the slow startup phase so they can be replayed
into the interactive process once it attaches.

Without this the user has to wait for the dev container to come up (~20 s for
image checks + tool freshness checks) before any typing reaches the inner shell.
Anything typed during that window is otherwise either lost or interpreted by the
parent shell after the CLI exits.
"""

from __future__ import annotations

import os
import sys
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_DISABLE_ENV = "AI_SHELL_NO_TYPEAHEAD"


class TypeaheadBuffer:
    """Thread-safe accumulator for raw stdin bytes."""

    def __init__(self) -> None:
        self._chunks: list[bytes] = []
        self._lock = threading.Lock()

    def append(self, data: bytes) -> None:
        if not data:
            return
        with self._lock:
            self._chunks.append(data)

    def bytes(self) -> bytes:
        with self._lock:
            return b"".join(self._chunks)


def _capture_disabled() -> bool:
    if os.environ.get(_DISABLE_ENV):
        return True
    try:
        return not sys.stdin.isatty()
    except (ValueError, OSError):
        return True


@contextmanager
def capture_typeahead() -> Iterator[TypeaheadBuffer]:
    """Drain stdin into an in-memory buffer until the context exits.

    No-op when stdin isn't a TTY or when ``AI_SHELL_NO_TYPEAHEAD=1`` is set; in
    those cases the yielded buffer stays empty and the caller falls back to the
    existing path.
    """
    buf = TypeaheadBuffer()

    if sys.platform == "win32" or _capture_disabled():
        yield buf
        return

    # Imports are guarded behind the platform check above because termios/tty
    # are POSIX-only.
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)
    stop = threading.Event()

    def _drain() -> None:
        while not stop.is_set():
            try:
                ready, _, _ = select.select([fd], [], [], 0.05)
            except (OSError, ValueError):
                return
            if fd in ready:
                try:
                    chunk = os.read(fd, 4096)
                except (OSError, BlockingIOError):
                    continue
                if not chunk:
                    return
                buf.append(chunk)

    try:
        tty.setcbreak(fd)
        thread = threading.Thread(target=_drain, daemon=True)
        thread.start()
        try:
            yield buf
        finally:
            stop.set()
            thread.join(timeout=0.5)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original)
