"""Drive ``claude auth login`` from the host instead of through the container TTY.

Inside a dev container the OAuth callback can never reach Claude Code, so
login falls back to the manual flow: Claude prints a ~600 character
authorize URL and waits for the code the browser shows afterwards. Doing
that through ``docker exec -it`` on Windows is fragile in two ways:

* The URL wraps in the TTY and a copied, mangled URL still signs you in,
  but with a broken ``state``; the code then fails with "That code wasn't
  accepted ... from an earlier sign-in attempt".
* Pasting the code into the Ink prompt through ConPTY often drops it.

``claude auth login`` behaves well without a TTY: it prints the URL on one
line and reads the code from standard input. So this module runs it over
pipes, opens the URL itself (in the account's host Chrome through the
DevTools port when there is one), and takes the code from a plain prompt
on the host terminal.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
from collections.abc import Callable
from http.client import HTTPConnection, HTTPException
from queue import Empty, Queue

logger = logging.getLogger(__name__)

LOGIN_URL_PATTERN = re.compile(r"https://\S+oauth\S*", re.IGNORECASE)
LOGIN_URL_TIMEOUT_SECONDS = 45.0
LOGIN_EXIT_TIMEOUT_SECONDS = 120.0
LOGIN_SUCCESS_MARKER = "Login successful"


def extract_login_url(line: str) -> str | None:
    """Return the OAuth authorize URL in *line*, or ``None``."""
    match = LOGIN_URL_PATTERN.search(line)
    if match is None:
        return None
    # Claude prints the URL followed by nothing, but be safe about trailing
    # punctuation from any wrapper text.
    return match.group(0).rstrip(".,)")


def open_in_chrome(port: int, url: str) -> bool:
    """Open *url* as a new tab in the host Chrome listening on *port*.

    Uses the DevTools HTTP endpoint ``PUT /json/new?<url>`` from the host,
    so the tab lands in the account's own profile window. Returns ``True``
    when Chrome accepted the request.
    """
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        # Chrome takes everything after ``?`` verbatim as the URL to open.
        connection.request("PUT", f"/json/new?{url}")
        response = connection.getresponse()
        response.read()
        return response.status == 200
    except (OSError, HTTPException) as exc:
        logger.debug("Could not open login URL in Chrome on port %s: %s", port, exc)
        return False
    finally:
        connection.close()


def _pump(stream: object, queue: Queue[str | None]) -> None:
    for line in iter(stream.readline, ""):  # type: ignore[attr-defined]
        queue.put(line)
    queue.put(None)


def run_piped_login(
    args: list[str],
    *,
    open_url: Callable[[str], bool],
    prompt_code: Callable[[], str],
    echo: Callable[[str], None] | None = None,
    url_timeout: float = LOGIN_URL_TIMEOUT_SECONDS,
    exit_timeout: float = LOGIN_EXIT_TIMEOUT_SECONDS,
) -> int | None:
    """Run *args* (a ``claude auth login`` command) over pipes.

    Waits for the authorize URL, hands it to *open_url*, asks *prompt_code*
    for the code and writes it to the process. Returns the exit code, or
    ``None`` when no URL appeared within *url_timeout* (the caller should
    fall back to an interactive login). *echo* receives every other output
    line so the user still sees what Claude says.
    """
    echo = echo or (lambda _line: None)
    logger.debug("piped login: %s", " ".join(args))
    proc = subprocess.Popen(  # noqa: S603
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdin is not None and proc.stdout is not None
    lines: Queue[str | None] = Queue()
    threading.Thread(target=_pump, args=(proc.stdout, lines), daemon=True).start()

    url: str | None = None
    finished = False
    output: list[str] = []
    try:
        while url is None and not finished:
            try:
                line = lines.get(timeout=url_timeout)
            except Empty:
                break
            if line is None:
                finished = True
                break
            output.append(line)
            url = extract_login_url(line)
            if url is None:
                echo(line.rstrip("\n"))

        if url is None:
            proc.kill()
            proc.wait()
            logger.debug("piped login: no URL seen; output was %r", "".join(output))
            return None

        if not open_url(url):
            echo("Open this URL in a browser signed in as the account:")
            echo(url)

        code = prompt_code().strip()
        if not code:
            proc.kill()
            proc.wait()
            return 1
        proc.stdin.write(code + "\n")
        proc.stdin.flush()
        proc.stdin.close()

        # Drain the rest so the user sees "Login successful" or the error.
        while True:
            try:
                line = lines.get(timeout=exit_timeout)
            except Empty:
                proc.kill()
                break
            if line is None:
                break
            text = line.rstrip("\n")
            # The prompt line itself has no newline until the code is typed;
            # strip it so only Claude's verdict is echoed.
            text = text.replace("Paste code here if prompted >", "").strip()
            if text:
                echo(text)
            output.append(line)
        return proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def login_succeeded(exit_code: int | None) -> bool:
    """True when :func:`run_piped_login` reports success."""
    return exit_code == 0
