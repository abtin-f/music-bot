"""In-memory download queue with global workers and per-user quotas."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Awaitable, Protocol

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from bot.config import Config
from bot.database.db import Database
from bot.downloader.spotify import SpotifyLink
from bot.utils.exceptions import UserFacingError

logger = logging.getLogger(__name__)


class QueueFullError(UserFacingError):
    def __init__(self) -> None:
        super().__init__(
            "The download queue is full right now — please try again in a few minutes."
        )


class UserLimitError(UserFacingError):
    def __init__(self, limit: int) -> None:
        super().__init__(
            f"You already have {limit} active download(s). "
            "Wait for them to finish first."
        )


@dataclass(slots=True)
class DownloadJob:
    user_id: int
    chat_id: int
    status_message_id: int
    link: SpotifyLink
    bitrate: str


class JobProcessor(Protocol):
    def __call__(
        self, job: DownloadJob, *, bot: Bot, db: Database, config: Config
    ) -> Awaitable[None]: ...


class DownloadQueue:
    """FIFO queue drained by N worker tasks.

    Slots are claimed with :meth:`reserve` *before* the job object exists
    (the status message has to be sent first), so two rapid-fire requests
    can never both slip past the per-user limit.
    """

    def __init__(
        self, config: Config, bot: Bot, db: Database, processor: JobProcessor
    ) -> None:
        self._config = config
        self._bot = bot
        self._db = db
        self._processor = processor
        self._queue: asyncio.Queue[DownloadJob] = asyncio.Queue()
        self._active: dict[int, int] = {}
        self._pending_total = 0
        self._workers: list[asyncio.Task] = []

    def active_for(self, user_id: int) -> int:
        return self._active.get(user_id, 0)

    def reserve(self, user_id: int) -> None:
        """Claim a queue slot for the user or raise a :class:`UserFacingError`."""
        if self._pending_total >= self._config.queue_max_size:
            raise QueueFullError()
        if self.active_for(user_id) >= self._config.max_active_jobs_per_user:
            raise UserLimitError(self._config.max_active_jobs_per_user)
        self._pending_total += 1
        self._active[user_id] = self.active_for(user_id) + 1

    def release(self, user_id: int) -> None:
        self._pending_total = max(0, self._pending_total - 1)
        remaining = self.active_for(user_id) - 1
        if remaining <= 0:
            self._active.pop(user_id, None)
        else:
            self._active[user_id] = remaining

    def submit(self, job: DownloadJob) -> int:
        """Enqueue a previously reserved job. Returns the queue position."""
        self._queue.put_nowait(job)
        return self._queue.qsize()

    async def start(self) -> None:
        for index in range(self._config.max_concurrent_downloads):
            self._workers.append(
                asyncio.create_task(self._worker(index), name=f"download-worker-{index}")
            )

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        # Jobs no worker ever picked up: tell their owners to resend instead
        # of leaving them staring at a frozen "Queued…" message.
        while True:
            try:
                job = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self.release(job.user_id)
            with contextlib.suppress(TelegramAPIError):
                await self._bot.edit_message_text(
                    "🔁 The bot restarted before this job started — "
                    "please send the link again.",
                    chat_id=job.chat_id,
                    message_id=job.status_message_id,
                )

    async def _worker(self, index: int) -> None:
        logger.info("Download worker %d started", index)
        while True:
            job = await self._queue.get()
            try:
                await self._processor(
                    job, bot=self._bot, db=self._db, config=self._config
                )
            except Exception:
                # process_job handles its own errors; this is a last resort.
                logger.exception(
                    "Worker %d: unhandled error processing job for user %d",
                    index,
                    job.user_id,
                )
            finally:
                self.release(job.user_id)
                self._queue.task_done()
