"""/settings — per-user audio quality stored in the database."""

from __future__ import annotations

import contextlib

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.config import ALLOWED_BITRATES, DEFAULT_BITRATE
from bot.database.db import Database
from bot.database.models import User
from bot.keyboards.inline import settings_kb

router = Router(name="settings")

_TEXT = (
    "⚙️ <b>Settings</b>\n\n"
    "🎚 <b>Audio quality</b>: <code>{bitrate}</code>\n"
    "Higher bitrate = better quality, larger files."
)


@router.message(Command("settings"))
async def cmd_settings(message: Message, db_user: User | None) -> None:
    bitrate = db_user.bitrate if db_user else DEFAULT_BITRATE
    await message.answer(
        _TEXT.format(bitrate=bitrate), reply_markup=settings_kb(bitrate)
    )


@router.callback_query(F.data == "menu:settings")
async def cb_settings(callback: CallbackQuery, db_user: User | None) -> None:
    bitrate = db_user.bitrate if db_user else DEFAULT_BITRATE
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(
            _TEXT.format(bitrate=bitrate), reply_markup=settings_kb(bitrate)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("settings:bitrate:"))
async def cb_set_bitrate(callback: CallbackQuery, db: Database) -> None:
    value = callback.data.rsplit(":", 1)[-1]
    if value not in ALLOWED_BITRATES:  # never trust callback payloads
        await callback.answer("Invalid option.", show_alert=True)
        return
    await db.set_bitrate(callback.from_user.id, value)
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(
            _TEXT.format(bitrate=value), reply_markup=settings_kb(value)
        )
    await callback.answer(f"Quality set to {value} ✅")
