"""Inline keyboards. Callback data uses short namespaced tokens
("menu:help", "settings:bitrate:320k", …) that handlers validate strictly.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import ALLOWED_BITRATES


def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="ℹ️ Help", callback_data="menu:help")
    builder.button(text="⚙️ Settings", callback_data="menu:settings")
    builder.button(text="📊 My stats", callback_data="menu:stats")
    builder.button(text="🤖 About", callback_data="menu:about")
    builder.adjust(2, 2)
    return builder.as_markup()


def back_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back", callback_data="menu:home")
    return builder.as_markup()


def settings_kb(current_bitrate: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for bitrate in ALLOWED_BITRATES:
        marker = "✅ " if bitrate == current_bitrate else ""
        builder.button(
            text=f"{marker}{bitrate}", callback_data=f"settings:bitrate:{bitrate}"
        )
    builder.button(text="⬅️ Back", callback_data="menu:home")
    builder.adjust(len(ALLOWED_BITRATES), 1)
    return builder.as_markup()


def admin_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📈 Statistics", callback_data="admin:stats")
    builder.button(text="📢 Broadcast", callback_data="admin:broadcast")
    builder.button(text="🧾 Error log", callback_data="admin:errors")
    builder.button(text="❌ Close", callback_data="admin:close")
    builder.adjust(2, 2)
    return builder.as_markup()


def admin_back_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back", callback_data="admin:home")
    return builder.as_markup()


def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Send", callback_data="bcast:confirm")
    builder.button(text="❌ Cancel", callback_data="bcast:cancel")
    builder.adjust(2)
    return builder.as_markup()
