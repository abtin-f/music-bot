"""The core flow: user sends a Spotify link → validate → queue a job."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from bot.config import DEFAULT_BITRATE, Config
from bot.database.models import User
from bot.downloader.spotify import parse_spotify_url
from bot.services.queue import DownloadJob, DownloadQueue
from bot.utils.exceptions import UserFacingError

router = Router(name="download")

_KIND_EMOJI = {"track": "🎵", "album": "💿", "playlist": "📃"}

_INVALID_LINK = (
    "🤔 That looks Spotify-related, but I can't use it.\n\n"
    "Please send a full link like:\n"
    "<code>https://open.spotify.com/track/…</code>\n"
    "<code>https://open.spotify.com/album/…</code>\n"
    "<code>https://open.spotify.com/playlist/…</code>\n\n"
    "💡 Short <code>spotify.link</code> URLs aren't supported — open them in "
    "a browser first and copy the full address."
)

_HINT = (
    "🎧 Send me a <b>Spotify link</b> (track, album, or playlist) and I'll "
    "fetch the music for you.\n\nNeed help? Use /help"
)


@router.message(F.text, StateFilter(None))
async def handle_text(
    message: Message,
    config: Config,
    db_user: User | None,
    queue: DownloadQueue,
) -> None:
    text = message.text or ""
    link = parse_spotify_url(text)
    if link is None:
        if "spotify" in text.lower():
            await message.reply(_INVALID_LINK)
        else:
            await message.reply(_HINT)
        return

    user_id = message.from_user.id
    try:
        queue.reserve(user_id)  # claim the slot before any awaits — no races
    except UserFacingError as exc:
        await message.reply(f"⚠️ {exc.user_message}")
        return

    try:
        status = await message.reply(
            f"⏳ <b>Queued…</b> {_KIND_EMOJI[link.kind]} {link.kind}"
        )
    except Exception:
        queue.release(user_id)
        raise

    bitrate = db_user.bitrate if db_user else DEFAULT_BITRATE
    queue.submit(
        DownloadJob(
            user_id=user_id,
            chat_id=message.chat.id,
            status_message_id=status.message_id,
            link=link,
            bitrate=bitrate,
        )
    )


@router.message(StateFilter(None))
async def handle_other(message: Message) -> None:
    """Anything that isn't text (stickers, photos, …) gets a gentle hint."""
    await message.reply(_HINT)
