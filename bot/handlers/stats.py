"""/stats — personal statistics plus public bot totals."""

from __future__ import annotations

import contextlib

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.database.db import Database
from bot.keyboards.inline import back_kb

router = Router(name="stats")


async def _stats_text(db: Database, user_id: int) -> str:
    user = await db.get_user(user_id)
    stats = await db.global_stats()
    member_since = (user.joined_at or "").split(" ")[0] if user else "—"
    downloads = user.downloads if user else 0
    return (
        "📊 <b>Your stats</b>\n"
        f"⬇️ Tracks received: <b>{downloads}</b>\n"
        f"📅 Member since: {member_since}\n\n"
        "🌍 <b>Bot totals</b>\n"
        f"👥 Users: {stats.total_users}\n"
        f"🎵 Tracks delivered: {stats.tracks_sent}"
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database) -> None:
    await message.answer(await _stats_text(db, message.from_user.id))


@router.callback_query(F.data == "menu:stats")
async def cb_stats(callback: CallbackQuery, db: Database) -> None:
    text = await _stats_text(db, callback.from_user.id)
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=back_kb())
    await callback.answer()
