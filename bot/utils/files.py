"""Filesystem helpers for temporary download directories."""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path


# Directories of jobs currently in flight. The periodic sweeper must never
# touch them: a long upload phase freezes a dir's mtime, so age alone is not
# proof that a directory is abandoned.
_ACTIVE_DIRS: set[Path] = set()


def create_job_dir(root: Path) -> Path:
    """Create a unique working directory for one download job.

    Directory names are random UUIDs — user input never becomes part of a
    filesystem path, which rules out path traversal by construction.
    """
    job_dir = root / uuid.uuid4().hex
    job_dir.mkdir(parents=True, exist_ok=False)
    _ACTIVE_DIRS.add(job_dir)
    return job_dir


def release_job_dir(job_dir: Path) -> None:
    """Mark a job directory as no longer in use (safe to sweep)."""
    _ACTIVE_DIRS.discard(job_dir)


def cleanup_stale_dirs(root: Path, max_age_minutes: int) -> int:
    """Delete job directories older than ``max_age_minutes``. Returns count.

    Blocking — call through ``asyncio.to_thread``.
    """
    if not root.exists():
        return 0
    cutoff = time.time() - max_age_minutes * 60
    removed = 0
    for child in root.iterdir():
        if not child.is_dir() or child in _ACTIVE_DIRS:
            continue
        try:
            if child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed
