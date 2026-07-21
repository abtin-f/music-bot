"""Admin panel: stats, broadcast, error log, ban/unban.

The whole router is gated by :class:`IsAdmin`, so nothing here is reachable
by regular users.
"""

from __future__ import annotations

import asyncio
import contextlib
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import BaseFilter, Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.database.db import Database
from bot.keyboards.inline import admin_back_kb, admin_kb, broadcast_confirm_kb
from bot.services.broadcast import run_broadcast_and_report

router = Router(name="admin")


class IsAdmin(BaseFilter):
    async def __call__(
        self, event: Message | CallbackQuery, config: Config
    ) -> bool:
        return event.from_user is not None and config.is_admin(event.from_user.id)


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class BroadcastStates(StatesGroup):
    waiting_message = State()
    waiting_confirm = State()


_PANEL = (
    "🛠 <b>Admin panel</b>\n\n"
    "Quick commands:\n"
    "<code>/ban &lt;user_id&gt;</code> – ban a user\n"
    "<code>/unban &lt;user_id&gt;</code> – unban a user"
)


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()  # escape hatch out of a half-finished broadcast
    await message.answer(_PANEL, reply_markup=admin_kb())


@router.callback_query(F.data == "admin:home")
async def cb_admin_home(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(_PANEL, reply_markup=admin_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:close")
async def cb_admin_close(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.delete()
    await callback.answer()


@router.callback_query(F.data == "admin:stats")
async def cb_admin_stats(callback: CallbackQuery, db: Database) -> None:
    stats = await db.global_stats()
    text = (
        "📈 <b>Bot statistics</b>\n\n"
        f"👥 Total users: <b>{stats.total_users}</b>\n"
        f"🚫 Banned: {stats.banned_users}\n"
        f"🟢 Active (24h): {stats.active_24h}\n"
        f"🟢 Active (7d): {stats.active_7d}\n\n"
        f"⬇️ Download jobs: {stats.total_jobs} "
        f"(✅ {stats.successful_jobs} / ❌ {stats.failed_jobs})\n"
        f"🎵 Tracks delivered: {stats.tracks_sent}\n"
        f"📅 Jobs today: {stats.jobs_today}"
    )
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=admin_back_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:errors")
async def cb_admin_errors(callback: CallbackQuery, config: Config) -> None:
    tail = ""
    if config.error_log_path.exists():
        lines = config.error_log_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
        tail = "\n".join(lines[-30:]).strip()
    if tail:
        text = (
            "🧾 <b>Error log</b> (most recent lines)\n\n"
            f"<pre>{escape(tail[-3500:])}</pre>"
        )
    else:
        text = "🧾 <b>Error log</b>\n\nNo errors logged 🎉"
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=admin_back_kb())
    await callback.answer()


# ------------------------------------------------------------------ broadcast


@router.callback_query(F.data == "admin:broadcast")
async def cb_broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BroadcastStates.waiting_message)
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(
            "📢 Send me the message to broadcast (text, photo — anything).\n\n"
            "Use /cancel to abort."
        )
    await callback.answer()


@router.message(Command("cancel"), StateFilter(BroadcastStates))
async def cmd_broadcast_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❎ Broadcast cancelled.")


@router.message(BroadcastStates.waiting_message)
async def broadcast_got_message(
    message: Message, state: FSMContext, db: Database
) -> None:
    await state.update_data(chat_id=message.chat.id, message_id=message.message_id)
    await state.set_state(BroadcastStates.waiting_confirm)
    count = len(await db.get_user_ids())
    await message.answer(
        f"Send this message to <b>{count}</b> users?",
        reply_markup=broadcast_confirm_kb(),
    )


@router.callback_query(F.data == "bcast:confirm", BroadcastStates.waiting_confirm)
async def cb_broadcast_confirm(
    callback: CallbackQuery, state: FSMContext, bot: Bot, db: Database
) -> None:
    data = await state.get_data()
    await state.clear()
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(
            "📤 Broadcasting… you'll get a report when it's done."
        )
    asyncio.create_task(
        run_broadcast_and_report(
            bot,
            db,
            from_chat_id=data["chat_id"],
            message_id=data["message_id"],
            report_chat_id=callback.message.chat.id,
        )
    )
    await callback.answer()


@router.callback_query(F.data == "bcast:cancel", BroadcastStates.waiting_confirm)
async def cb_broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text("❎ Broadcast cancelled.")
    await callback.answer()


# ------------------------------------------------------------------ ban/unban


def _parse_user_id(args: str | None) -> int | None:
    if not args:
        return None
    candidate = args.strip().split()[0]
    return int(candidate) if candidate.isdigit() else None


@router.message(Command("ban"))
async def cmd_ban(
    message: Message, command: CommandObject, db: Database, config: Config
) -> None:
    target = _parse_user_id(command.args)
    if target is None:
        await message.answer("Usage: <code>/ban &lt;user_id&gt;</code>")
        return
    if config.is_admin(target):
        await message.answer("🙅 You can't ban an admin.")
        return
    if await db.set_banned(target, True):
        await message.answer(f"🚫 User <code>{target}</code> banned.")
    else:
        await message.answer("User not found in the database.")


@router.message(Command("unban"))
async def cmd_unban(
    message: Message, command: CommandObject, db: Database
) -> None:
    target = _parse_user_id(command.args)
    if target is None:
        await message.answer("Usage: <code>/unban &lt;user_id&gt;</code>")
        return
    if await db.set_banned(target, False):
        await message.answer(f"✅ User <code>{target}</code> unbanned.")
    else:
        await message.answer("User not found in the database.")
