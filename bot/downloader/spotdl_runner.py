"""Thin async wrapper around the spotDL command-line interface.

spotDL runs as a subprocess (``python -m spotdl``) rather than through its
Python API: the CLI is the stable documented surface, and a crashing download
can never take the bot process down with it. The URL is passed as a single
argv element with no shell involved, so command injection is impossible.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys
from dataclasses import dataclass
from pathlib import Path

from bot.config import Config
from bot.utils.exceptions import UserFacingError

logger = logging.getLogger(__name__)


class DownloadFailedError(UserFacingError):
    pass


@dataclass(frozen=True, slots=True)
class DownloadResult:
    files: tuple[Path, ...]
    log_tail: str


# Known spotDL failure fingerprints mapped to friendly messages.
_ERROR_HINTS: tuple[tuple[str, str], ...] = (
    ("LookupError", "No downloadable match was found for this content."),
    ("No results found", "No downloadable match was found for this content."),
    ("AudioProviderError", "The audio source rejected the download — try again later."),
    ("SpotifyError", "Spotify rejected the request — the link may be private or removed."),
    ("YT-DLP", "The audio source failed to deliver the file — try again later."),
)


def _kill_proc_tree(proc: asyncio.subprocess.Process) -> None:
    """Best-effort kill of spotDL and (on POSIX) its ffmpeg children."""
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()  # Windows has no POSIX process groups


def _map_error(log: str) -> str:
    for needle, message in _ERROR_HINTS:
        if needle.lower() in log.lower():
            return message
    return "Download failed — please try again later."


async def run_spotdl(
    url: str, out_dir: Path, bitrate: str, config: Config
) -> DownloadResult:
    """Download ``url`` into ``out_dir`` as tagged MP3s via spotDL."""
    cmd = [
        sys.executable,
        "-m",
        "spotdl",
        "download",
        url,
        "--output",
        str(out_dir / "{artists} - {title}.{output-ext}"),
        "--format",
        "mp3",
        "--bitrate",
        bitrate,
        "--print-errors",
    ]
    if config.audio_providers:
        cmd += ["--audio", *config.audio_providers]
    if config.cookie_file and config.cookie_file.exists():
        cmd += ["--cookie-file", str(config.cookie_file)]
    if config.spotify_client_id and config.spotify_client_secret:
        cmd += [
            "--client-id",
            config.spotify_client_id,
            "--client-secret",
            config.spotify_client_secret,
        ]

    logger.info("Running spotDL for %s (bitrate=%s)", url, bitrate)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(out_dir),
        # Own process group on POSIX so a kill also takes ffmpeg children.
        start_new_session=(os.name == "posix"),
    )
    try:
        raw, _ = await asyncio.wait_for(
            proc.communicate(), timeout=config.download_timeout
        )
    except asyncio.CancelledError:
        # Bot is shutting down — never leave an orphaned spotDL behind.
        _kill_proc_tree(proc)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=5)
        raise
    except asyncio.TimeoutError:
        _kill_proc_tree(proc)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=5)
        raise DownloadFailedError(
            "Download timed out — the content may be too large."
        ) from None

    log = raw.decode("utf-8", errors="replace")
    log_tail = "\n".join(log.splitlines()[-25:])

    files = tuple(sorted(p for p in out_dir.glob("*.mp3") if p.is_file()))
    if not files:
        logger.warning(
            "spotDL produced no files (rc=%s) for %s:\n%s",
            proc.returncode,
            url,
            log_tail,
        )
        raise DownloadFailedError(_map_error(log))

    logger.info("spotDL finished: %d file(s) for %s", len(files), url)
    return DownloadResult(files=files, log_tail=log_tail)
