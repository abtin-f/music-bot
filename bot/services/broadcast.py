"""Admin broadcast: copy one message to every non-banned user."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

from bot.database.db import Database

logger = logging.getLogger(__name__)


async def run_broadcast_and_report(
    bot: Bot,
    db: Database,
    from_chat_id: int,
    message_id: int,
    report_chat_id: int,
) -> None:
    """Send the stored message to all users, then report the result.

    Designed to run as a background task so the admin handler returns
    immediately.
    """
    user_ids = await db.get_user_ids()
    sent = 0
    failed = 0
    for user_id in user_ids:
        try:
            await bot.copy_message(
                chat_id=user_id, from_chat_id=from_chat_id, message_id=message_id
            )
            sent += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
            try:
                await bot.copy_message(
                    chat_id=user_id, from_chat_id=from_chat_id, message_id=message_id
                )
                sent += 1
            except TelegramAPIError:
                failed += 1
        except TelegramAPIError:
            failed += 1  # user blocked the bot, deleted the account, etc.
        except Exception:
            logger.exception("Broadcast: unexpected error for user %d", user_id)
            failed += 1
        await asyncio.sleep(0.05)  # ~20 msg/s keeps us under the global flood limit

    logger.info("Broadcast finished: %d delivered, %d failed", sent, failed)
    with contextlib.suppress(TelegramAPIError):
        await bot.send_message(
            report_chat_id,
            f"📢 Broadcast finished: ✅ {sent} delivered, ❌ {failed} failed.",
        )
