"""Simple per-user rate limiter for incoming messages and callback queries.

Registered as an OUTER middleware ahead of AccessMiddleware, so floods are
dropped before they cause any database work. Updates arriving faster than
the cooldown are discarded; the user gets exactly one warning until they
slow down again. Admins are exempt.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config import Config


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, cooldown: float) -> None:
        self._cooldown = cooldown
        self._last_seen: dict[int, float] = {}
        self._warned: set[int] = set()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        config: Config = data["config"]
        if self._cooldown <= 0 or user is None or config.is_admin(user.id):
            return await handler(event, data)

        now = time.monotonic()
        if now - self._last_seen.get(user.id, 0.0) < self._cooldown:
            await self._reject(event, user.id)
            return None

        self._last_seen[user.id] = now
        self._warned.discard(user.id)
        if len(self._last_seen) > 50_000:  # keep memory bounded on busy bots
            self._last_seen.clear()
            self._warned.clear()
        return await handler(event, data)

    async def _reject(self, event: TelegramObject, user_id: int) -> None:
        first_offense = user_id not in self._warned
        self._warned.add(user_id)
        with contextlib.suppress(TelegramAPIError):
            if isinstance(event, CallbackQuery):
                # Always answer callbacks — an ignored one leaves the client
                # showing a loading spinner for several seconds.
                await event.answer("⏱ Not so fast!" if first_offense else None)
            elif isinstance(event, Message) and first_offense:
                await event.answer("⏱ Slow down a little — try again in a moment.")
