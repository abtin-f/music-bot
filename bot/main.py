"""Application entry point: wires config, database, queue, and dispatcher."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat

from bot.config import Config
from bot.database.db import Database
from bot.handlers import setup_routers
from bot.middlewares.access import AccessMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.services.processor import process_job
from bot.services.queue import DownloadQueue
from bot.utils.files import cleanup_stale_dirs
from bot.utils.logger import setup_logging

logger = logging.getLogger(__name__)


class _HealthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP endpoint so PaaS platforms (Render, Koyeb, HF Spaces)
    that require an open port keep the polling bot alive."""

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Spotify music bot is running.")

    def log_message(self, *args) -> None:  # silence default request logging
        pass


def _start_health_server() -> None:
    """Bind to the platform-provided PORT in a daemon thread (no-op if unset
    and default 8080 is unavailable)."""
    port = int(os.getenv("PORT", "8080"))
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), _HealthHandler)
    except OSError as exc:
        logger.warning("Health server could not bind to port %d: %s", port, exc)
        return
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info("Health server listening on port %d", port)

_USER_COMMANDS = [
    BotCommand(command="start", description="Start the bot"),
    BotCommand(command="help", description="How to use"),
    BotCommand(command="settings", description="Audio quality"),
    BotCommand(command="stats", description="Your statistics"),
    BotCommand(command="about", description="About this bot"),
]


async def _set_bot_commands(bot: Bot, config: Config) -> None:
    await bot.set_my_commands(_USER_COMMANDS)
    admin_commands = _USER_COMMANDS + [
        BotCommand(command="admin", description="Admin panel")
    ]
    for admin_id in config.admin_ids:
        # Fails for admins who never started the bot — that's fine.
        with contextlib.suppress(TelegramAPIError):
            await bot.set_my_commands(
                admin_commands, scope=BotCommandScopeChat(chat_id=admin_id)
            )


async def _periodic_cleanup(config: Config) -> None:
    """Safety net for temp dirs orphaned by crashes or restarts."""
    while True:
        await asyncio.sleep(30 * 60)
        try:
            removed = await asyncio.to_thread(
                cleanup_stale_dirs, config.downloads_dir, config.cleanup_max_age_minutes
            )
            if removed:
                logger.info("Cleanup: removed %d stale job dir(s)", removed)
        except Exception:
            logger.exception("Periodic cleanup failed")


async def main() -> None:
    config = Config.from_env()
    setup_logging(config)
    _start_health_server()
    config.downloads_dir.mkdir(parents=True, exist_ok=True)

    db = Database(config.database_path)
    await db.connect()

    session = AiohttpSession(proxy=config.telegram_proxy) if config.telegram_proxy else None
    bot = Bot(
        token=config.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage(), config=config, db=db)

    queue = DownloadQueue(config=config, bot=bot, db=db, processor=process_job)
    dp["queue"] = queue

    # Order matters: throttling runs first so floods never reach the
    # database; AccessMiddleware then registers the user and enforces bans.
    access = AccessMiddleware()
    dp.message.outer_middleware(ThrottlingMiddleware(cooldown=config.rate_limit_seconds))
    dp.callback_query.outer_middleware(
        ThrottlingMiddleware(cooldown=min(1.0, config.rate_limit_seconds))
    )
    dp.message.outer_middleware(access)
    dp.callback_query.outer_middleware(access)

    setup_routers(dp)

    # Purge anything left over from a previous run, then start the safety net.
    await asyncio.to_thread(cleanup_stale_dirs, config.downloads_dir, 0)
    cleanup_task = asyncio.create_task(_periodic_cleanup(config))
    await queue.start()

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await _set_bot_commands(bot, config)
        logger.info("Bot started (workers=%d)", config.max_concurrent_downloads)
        await dp.start_polling(bot)
    finally:
        cleanup_task.cancel()
        await queue.stop()
        await db.close()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt, SystemExit):
        asyncio.run(main())
