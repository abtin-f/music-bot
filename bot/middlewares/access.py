"""Outer middleware: registers every user in the database and blocks banned
users before any handler runs. Injects ``db_user`` into handler data.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config import Config
from bot.database.db import Database

logger = logging.getLogger(__name__)

_BAN_NOTICE_COOLDOWN = 30.0  # seconds between "you are banned" replies per user


class AccessMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self._last_ban_notice: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.is_bot:
            # Anonymous admins / channel posts: handlers must tolerate None.
            data["db_user"] = None
            return await handler(event, data)

        db: Database = data["db"]
        config: Config = data["config"]

        # Cached check first — banned users must not cost a DB write per
        # update, and must not keep refreshing last_active in the stats.
        if db.is_banned_cached(user.id) and not config.is_admin(user.id):
            await self._notify_banned(event, user.id)
            return None  # swallow the update entirely

        record = await db.upsert_user(user.id, user.username, user.first_name)
        if record.is_banned and not config.is_admin(user.id):
            await self._notify_banned(event, user.id)
            return None

        data["db_user"] = record
        return await handler(event, data)

    async def _notify_banned(self, event: TelegramObject, user_id: int) -> None:
        now = time.monotonic()
        if now - self._last_ban_notice.get(user_id, 0.0) < _BAN_NOTICE_COOLDOWN:
            return
        self._last_ban_notice[user_id] = now
        try:
            if isinstance(event, CallbackQuery):
                await event.answer("🚫 You are banned from using this bot.", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("🚫 You are banned from using this bot.")
        except TelegramAPIError:
            logger.debug("Could not deliver ban notice to %d", user_id)
