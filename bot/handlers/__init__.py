"""Router registration. Order matters: the download catch-all goes last."""

from __future__ import annotations

from aiogram import Dispatcher

from bot.handlers import admin, download, settings, stats, user
from bot.handlers.errors import on_error


def setup_routers(dp: Dispatcher) -> None:
    dp.include_router(user.router)
    dp.include_router(settings.router)
    dp.include_router(stats.router)
    dp.include_router(admin.router)
    dp.include_router(download.router)  # text catch-all — keep last
    dp.errors.register(on_error)
