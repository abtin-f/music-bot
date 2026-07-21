"""Reads ID3 metadata from downloaded MP3s and prepares Telegram thumbnails.

Everything here is synchronous (mutagen and Pillow are blocking libraries)
and is expected to be called through ``asyncio.to_thread``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from mutagen.id3 import ID3
from mutagen.mp3 import MP3
from PIL import Image

logger = logging.getLogger(__name__)

# Telegram requires audio thumbnails to be JPEG, at most 320 px on a side.
THUMB_MAX_SIDE = 320


@dataclass(frozen=True, slots=True)
class TrackMeta:
    title: str
    artist: str | None
    album: str | None
    year: str | None
    duration: int
    thumb_path: Path | None


def _first_text(tags: ID3, key: str) -> str | None:
    frame = tags.get(key)
    if frame is not None and frame.text:
        value = str(frame.text[0]).strip()
        return value or None
    return None


def _make_thumbnail(data: bytes, target: Path) -> Path | None:
    try:
        with Image.open(BytesIO(data)) as img:
            img = img.convert("RGB")
            img.thumbnail((THUMB_MAX_SIDE, THUMB_MAX_SIDE))
            img.save(target, "JPEG", quality=85)
        return target
    except Exception:
        logger.warning("Failed to build thumbnail for %s", target, exc_info=True)
        return None


def read_track_meta(mp3_path: Path, work_dir: Path) -> TrackMeta:
    """Extract tags, duration, and an embedded-cover thumbnail from an MP3.

    Never raises: any unreadable field falls back to a sensible default so a
    single corrupt tag can't sink the whole upload.
    """
    title = mp3_path.stem
    artist = album = year = None
    duration = 0
    thumb_path: Path | None = None

    try:
        duration = int(MP3(mp3_path).info.length)
    except Exception:
        logger.warning("Could not read duration from %s", mp3_path, exc_info=True)

    try:
        tags = ID3(mp3_path)
        title = _first_text(tags, "TIT2") or title
        artist = _first_text(tags, "TPE1")
        album = _first_text(tags, "TALB")
        year = (_first_text(tags, "TDRC") or "")[:4] or None
        covers = tags.getall("APIC")
        if covers:
            thumb_path = _make_thumbnail(
                covers[0].data, work_dir / f"{mp3_path.stem}.thumb.jpg"
            )
    except Exception:
        logger.warning("Could not read ID3 tags from %s", mp3_path, exc_info=True)

    return TrackMeta(
        title=title,
        artist=artist,
        album=album,
        year=year,
        duration=duration,
        thumb_path=thumb_path,
    )
