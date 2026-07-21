"""The download pipeline: Spotify link → spotDL → tagged MP3s → Telegram.

One call to :func:`process_job` handles a full job lifecycle including the
editable progress message, error reporting, statistics, and cleanup of the
temporary working directory.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
from html import escape
from pathlib import Path

from aiogram import Bot
from aiogram.enums import ChatAction
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramEntityTooLarge,
    TelegramRetryAfter,
)
from aiogram.types import FSInputFile

from bot.config import Config
from bot.database.db import Database
from bot.downloader.spotdl_runner import run_spotdl
from bot.downloader.spotify import fetch_oembed
from bot.services.audio import TrackMeta, read_track_meta
from bot.services.queue import DownloadJob
from bot.utils.exceptions import UserFacingError
from bot.utils.files import create_job_dir, release_job_dir

logger = logging.getLogger(__name__)

# Telegram caps audio captions at 1024 chars (counted after entity parsing);
# clipping each tag field keeps even 3-field captions comfortably below it.
_MAX_FIELD = 256


def _clip(value: str, limit: int = _MAX_FIELD) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


class _Status:
    """Edits a single progress message. Edits are cosmetic and never raise."""

    def __init__(self, bot: Bot, chat_id: int, message_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._message_id = message_id

    async def set(self, text: str) -> None:
        try:
            await self._bot.edit_message_text(
                text, chat_id=self._chat_id, message_id=self._message_id
            )
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            with contextlib.suppress(TelegramAPIError):
                await self._bot.edit_message_text(
                    text, chat_id=self._chat_id, message_id=self._message_id
                )
        except TelegramAPIError:
            # Deleted message, network blip, blocked bot — a failed status
            # edit must never decide the fate of the actual download.
            logger.debug("Status edit failed", exc_info=True)


async def process_job(
    job: DownloadJob, *, bot: Bot, db: Database, config: Config
) -> None:
    status = _Status(bot, job.chat_id, job.status_message_id)
    job_dir = create_job_dir(config.downloads_dir)
    sent = 0
    error_text: str | None = None

    try:
        # A ban may have landed while the job sat in the queue.
        user = await db.get_user(job.user_id)
        if user is not None and user.is_banned:
            error_text = "user banned before processing"
            await status.set("❌ Cancelled.")
            return

        # Cache: a track delivered before is re-sent by file_id — instant,
        # no download, no external network beyond the Bot API itself.
        if job.link.kind == "track":
            cached_file_id = await db.get_cached_track(
                job.link.spotify_id, job.bitrate
            )
            if cached_file_id:
                try:
                    await bot.send_audio(chat_id=job.chat_id, audio=cached_file_id)
                except TelegramRetryAfter as exc:
                    await asyncio.sleep(exc.retry_after + 1)
                    await bot.send_audio(chat_id=job.chat_id, audio=cached_file_id)
                except TelegramBadRequest:
                    # file_id no longer valid — drop it and download fresh.
                    await db.delete_cached_track(job.link.spotify_id, job.bitrate)
                    cached_file_id = None
                if cached_file_id:
                    sent = 1
                    await status.set("✅ <b>Finished!</b> ⚡ Served from cache.")
                    return

        await status.set("🔍 <b>Reading Spotify…</b>")
        info = await fetch_oembed(job.link)
        if info and info.title:
            await status.set(f"🎵 <b>Downloading…</b>\n{escape(_clip(info.title))}")
        else:
            await status.set("🎵 <b>Downloading…</b>")

        result = await run_spotdl(
            job.link.canonical_url, job_dir, job.bitrate, config
        )

        await status.set("⚙️ <b>Processing…</b>")
        total = len(result.files)
        files = list(result.files[: config.max_playlist_tracks])
        truncated = total - len(files)
        metas = [
            await asyncio.to_thread(read_track_meta, path, job_dir) for path in files
        ]

        await status.set("📤 <b>Uploading…</b>")
        skipped_large = 0
        failed_tracks = 0
        limit_bytes = config.telegram_file_limit_mb * 1024 * 1024
        for path, meta in zip(files, metas):
            if db.is_banned_cached(job.user_id):
                error_text = "user banned mid-job"
                break
            if path.stat().st_size > limit_bytes:
                skipped_large += 1
                continue
            try:
                sent_message = await _send_track(bot, job.chat_id, path, meta)
                sent += 1
                # Remember the uploaded file so this track is instant next time.
                if job.link.kind == "track" and sent_message.audio is not None:
                    with contextlib.suppress(Exception):
                        await db.put_cached_track(
                            job.link.spotify_id,
                            job.bitrate,
                            sent_message.audio.file_id,
                            meta.title,
                        )
            except TelegramEntityTooLarge:
                skipped_large += 1
            except TelegramBadRequest:
                # One rejected track must not sink the rest of the batch.
                logger.warning(
                    "Telegram rejected track %s", path.name, exc_info=True
                )
                failed_tracks += 1
            if len(files) > 1:
                await asyncio.sleep(1.0)  # stay well under Telegram flood limits

        await status.set(
            _summary(
                sent, truncated, skipped_large, failed_tracks,
                config.max_playlist_tracks,
            )
        )
    except UserFacingError as exc:
        error_text = exc.user_message
        await status.set(f"❌ {escape(exc.user_message)}")
    except asyncio.CancelledError:
        # Shutdown while this job ran: leave an honest status behind.
        error_text = "cancelled by shutdown"
        await status.set("🔁 The bot is restarting — please send the link again.")
        raise
    except Exception as exc:
        logger.exception(
            "Job failed for user %s (%s)", job.user_id, job.link.canonical_url
        )
        error_text = f"{type(exc).__name__}: {exc}"
        await status.set("❌ <b>Something went wrong.</b> Please try again later.")
    finally:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(shutil.rmtree, job_dir, ignore_errors=True)
        release_job_dir(job_dir)
        outcome = "success" if sent > 0 and error_text is None else "failed"
        with contextlib.suppress(Exception):
            await db.add_download_record(
                job.user_id,
                job.link.canonical_url,
                job.link.kind,
                sent,
                outcome,
                error_text,
            )
            if sent:
                await db.bump_user_downloads(job.user_id, sent)


async def _send_track(bot: Bot, chat_id: int, path: Path, meta: TrackMeta):
    """Upload one MP3; returns the sent Message (for file_id caching)."""
    title = _clip(meta.title)
    artist = _clip(meta.artist) if meta.artist else None
    album = _clip(meta.album) if meta.album else None

    caption = f"🎵 <b>{escape(title)}</b>"
    if artist:
        caption += f"\n👤 {escape(artist)}"
    if album:
        caption += f"\n💿 {escape(album)}"
        if meta.year:
            caption += f" ({escape(meta.year)})"

    audio = FSInputFile(path)
    thumbnail = FSInputFile(meta.thumb_path) if meta.thumb_path else None
    with contextlib.suppress(TelegramBadRequest):
        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
    try:
        return await bot.send_audio(
            chat_id=chat_id,
            audio=audio,
            caption=caption,
            title=title,
            performer=artist,
            duration=meta.duration or None,
            thumbnail=thumbnail,
        )
    except TelegramRetryAfter as exc:
        # One polite retry after Telegram's requested cool-down.
        await asyncio.sleep(exc.retry_after + 1)
        return await bot.send_audio(
            chat_id=chat_id,
            audio=audio,
            caption=caption,
            title=title,
            performer=artist,
            duration=meta.duration or None,
            thumbnail=thumbnail,
        )


def _summary(
    sent: int, truncated: int, skipped_large: int, failed_tracks: int, cap: int
) -> str:
    if sent:
        lines = [f"✅ <b>Finished!</b> Sent {sent} track(s)."]
    else:
        lines = ["⚠️ <b>No tracks could be sent.</b>"]
    if skipped_large:
        lines.append(
            f"📦 {skipped_large} file(s) skipped — larger than the Telegram upload limit."
        )
    if failed_tracks:
        lines.append(f"⚠️ {failed_tracks} track(s) failed to upload.")
    if truncated > 0:
        lines.append(f"✂️ Only the first {cap} tracks were sent (playlist cap).")
    return "\n".join(lines)
