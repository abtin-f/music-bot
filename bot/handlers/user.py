"""Public commands: /start, /help, /about and the main-menu callbacks."""

from __future__ import annotations

import contextlib
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.keyboards.inline import back_kb, main_menu_kb

router = Router(name="user")

_WELCOME = (
    "👋 <b>Welcome, {name}!</b>\n\n"
    "I download music from <b>Spotify</b> links and send it back to you as "
    "high-quality MP3 🎧\n\n"
    "Just send me a link to a:\n"
    "•  🎵 Track\n"
    "•  💿 Album\n"
    "•  📃 Playlist\n\n"
    "Use the buttons below to get started."
)

_HELP = (
    "ℹ️ <b>How to use</b>\n\n"
    "1. Open Spotify and copy a share link.\n"
    "2. Paste it here.\n"
    "3. I fetch, tag, and send the MP3 back.\n\n"
    "<b>Supported links</b>\n"
    "<code>https://open.spotify.com/track/…</code>\n"
    "<code>https://open.spotify.com/album/…</code>\n"
    "<code>https://open.spotify.com/playlist/…</code>\n\n"
    "<b>Limits</b>\n"
    "• Max {max_tracks} tracks per album/playlist\n"
    "• Files over ~50 MB can't be uploaded by Telegram bots\n"
    "• {per_user} download job(s) at a time per user\n\n"
    "<b>Commands</b>\n"
    "/start – main menu\n"
    "/help – this help\n"
    "/settings – audio quality\n"
    "/stats – your statistics\n"
    "/about – about this bot"
)

_ABOUT = (
    "🤖 <b>Spotify Music Bot</b>\n\n"
    "Downloads music from Spotify links and delivers tagged, "
    "high-quality MP3s.\n\n"
    "<b>Tech</b>: Python · aiogram 3 · spotDL · FFmpeg\n"
    "<b>Quality</b>: up to 320 kbps MP3 with full metadata &amp; cover art\n\n"
    "⚠️ For personal use only. Please respect the rights of artists — "
    "if you love a track, support it on official platforms."
)


def _help_text(config: Config) -> str:
    return _HELP.format(
        max_tracks=config.max_playlist_tracks,
        per_user=config.max_active_jobs_per_user,
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()  # /start is the universal escape from any FSM flow
    name = escape(message.from_user.first_name or "there")
    await message.answer(_WELCOME.format(name=name), reply_markup=main_menu_kb())


@router.message(Command("help"))
async def cmd_help(message: Message, config: Config) -> None:
    await message.answer(_help_text(config))


@router.message(Command("about"))
async def cmd_about(message: Message) -> None:
    await message.answer(_ABOUT)


@router.callback_query(F.data == "menu:home")
async def cb_home(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    name = escape(callback.from_user.first_name or "there")
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(
            _WELCOME.format(name=name), reply_markup=main_menu_kb()
        )
    await callback.answer()


@router.callback_query(F.data == "menu:help")
async def cb_help(callback: CallbackQuery, config: Config) -> None:
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(_help_text(config), reply_markup=back_kb())
    await callback.answer()


@router.callback_query(F.data == "menu:about")
async def cb_about(callback: CallbackQuery) -> None:
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(_ABOUT, reply_markup=back_kb())
    await callback.answer()
