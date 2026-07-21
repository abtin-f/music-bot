"""Global error handler — logs everything, tells the user something gentle."""

from __future__ import annotations

import contextlib
import logging

from aiogram.types import ErrorEvent

logger = logging.getLogger(__name__)


async def on_error(event: ErrorEvent) -> bool:
    logger.error("Unhandled update error", exc_info=event.exception)
    update = event.update
    with contextlib.suppress(Exception):
        if update.message:
            await update.message.answer(
                "💥 <b>Unexpected error.</b> Please try again."
            )
        elif update.callback_query:
            await update.callback_query.answer(
                "💥 Unexpected error. Please try again.", show_alert=True
            )
    return True
