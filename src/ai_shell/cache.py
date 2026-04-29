"""Time-based filesystem cache for expensive preflight checks.

Used to avoid repeating slow operations (Docker image pulls, Bedrock auth
probes) on every launch.  Cache entries live under
``~/.cache/ai-shell/<namespace>/`` as small timestamp files keyed by a hash
of caller-provided strings.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _cache_path(namespace: str, key: str) -> Path:
    digest = hashlib.sha1(key.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    base = Path.home() / ".cache" / "ai-shell" / namespace
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{digest}.timestamp"


def is_fresh(namespace: str, key: str, ttl_seconds: int) -> bool:
    """Return True if a cache entry exists for *key* and is younger than the TTL."""
    if ttl_seconds <= 0:
        return False
    path = _cache_path(namespace, key)
    if not path.is_file():
        return False
    try:
        last = float(path.read_text().strip())
    except (OSError, ValueError):
        return False
    age = time.time() - last
    return age < ttl_seconds


def mark_fresh(namespace: str, key: str) -> None:
    """Stamp the cache entry for *key* with the current time."""
    path = _cache_path(namespace, key)
    try:
        path.write_text(f"{time.time()}\n")
    except OSError as e:
        logger.debug("Failed to write cache marker %s: %s", path, e)
