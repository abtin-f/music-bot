"""Spotify URL validation, parsing, and lightweight metadata lookup.

Metadata comes from Spotify's public oEmbed endpoint, which needs no API
credentials. It doubles as an early existence check: removed or private
content returns a 4xx before we ever spawn a download.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

import aiohttp

from bot.utils.exceptions import UserFacingError

OEMBED_ENDPOINT = "https://open.spotify.com/oembed"

# Strict pattern: only open.spotify.com links, only the three supported kinds,
# and exactly 22 base62 chars for the id. Everything else is rejected.
_SPOTIFY_RE = re.compile(
    r"https?://open\.spotify\.com/(?:intl-[A-Za-z-]+/)?"
    r"(?P<kind>track|album|playlist)/(?P<id>[A-Za-z0-9]{22})"
)


class LinkUnavailableError(UserFacingError):
    def __init__(self) -> None:
        super().__init__(
            "This content doesn't exist, was removed, or is a private playlist."
        )


@dataclass(frozen=True, slots=True)
class SpotifyLink:
    kind: str  # "track" | "album" | "playlist"
    spotify_id: str

    @property
    def canonical_url(self) -> str:
        # Rebuilt from validated parts — original query params never survive.
        return f"https://open.spotify.com/{self.kind}/{self.spotify_id}"


@dataclass(frozen=True, slots=True)
class OEmbedInfo:
    title: str | None
    thumbnail_url: str | None


def parse_spotify_url(text: str) -> SpotifyLink | None:
    """Find the first valid Spotify track/album/playlist URL in ``text``."""
    match = _SPOTIFY_RE.search(text)
    if match is None:
        return None
    return SpotifyLink(kind=match.group("kind"), spotify_id=match.group("id"))


async def fetch_oembed(link: SpotifyLink, timeout_seconds: float = 10) -> OEmbedInfo | None:
    """Fetch title/cover for a link.

    Raises :class:`LinkUnavailableError` when Spotify says the content is
    gone or inaccessible. Returns ``None`` on network trouble — the lookup
    is advisory, so the download still gets its chance.
    """
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    try:
        # trust_env honours HTTP(S)_PROXY — Spotify may only be reachable
        # through a proxy on some networks.
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.get(
                OEMBED_ENDPOINT, params={"url": link.canonical_url}
            ) as resp:
                if resp.status in (400, 404):
                    raise LinkUnavailableError()
                if resp.status != 200:
                    return None
                payload = await resp.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None
    return OEmbedInfo(
        title=payload.get("title") or None,
        thumbnail_url=payload.get("thumbnail_url") or None,
    )
