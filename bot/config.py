"""Application configuration.

All values come from environment variables (optionally loaded from a local
``.env`` file). Secrets are never hard-coded anywhere in the codebase.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Bitrates the user can pick in /settings (values are passed straight to spotDL).
ALLOWED_BITRATES: tuple[str, ...] = ("128k", "192k", "256k", "320k")
DEFAULT_BITRATE = "320k"

# spotDL audio providers we allow in SPOTDL_AUDIO_PROVIDERS. Strict allowlist:
# these values end up on the spotDL command line, nothing else may.
ALLOWED_AUDIO_PROVIDERS: frozenset[str] = frozenset(
    {"youtube", "youtube-music", "soundcloud", "bandcamp", "piped"}
)


def _parse_audio_providers(raw: str) -> tuple[str, ...]:
    """Parse a space/comma separated provider list, dropping unknown names."""
    return tuple(
        p for p in raw.replace(",", " ").split() if p in ALLOWED_AUDIO_PROVIDERS
    )


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, "").strip() or default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _parse_admin_ids(raw: str) -> tuple[int, ...]:
    """Parse a comma/semicolon separated list of Telegram user ids."""
    ids: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.lstrip("-").isdigit():
            ids.append(int(chunk))
    return tuple(ids)


@dataclass(frozen=True, slots=True)
class Config:
    """Immutable runtime configuration shared across the application."""

    bot_token: str
    admin_ids: tuple[int, ...]
    telegram_proxy: str | None

    database_path: Path
    downloads_dir: Path
    log_dir: Path

    max_concurrent_downloads: int  # global download worker count
    max_active_jobs_per_user: int  # queued + running jobs per user
    queue_max_size: int            # total queued jobs across all users
    max_playlist_tracks: int       # tracks sent per album/playlist job
    download_timeout: int          # seconds before a spotDL job is killed
    rate_limit_seconds: float      # min delay between messages per user
    telegram_file_limit_mb: int    # Bot API upload hard limit is 50 MB
    cleanup_max_age_minutes: int   # stale temp dirs older than this are purged

    spotify_client_id: str | None
    spotify_client_secret: str | None

    # Ordered spotDL audio providers; empty tuple = spotDL's own default.
    audio_providers: tuple[str, ...]

    # Netscape-format cookies.txt passed to yt-dlp (fixes YouTube bot checks).
    cookie_file: Path | None

    log_level: str

    @property
    def error_log_path(self) -> Path:
        return self.log_dir / "errors.log"

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids

    @classmethod
    def from_env(cls) -> Config:
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "BOT_TOKEN is not set. Copy .env.example to .env and fill in your token."
            )
        return cls(
            bot_token=token,
            admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS", "")),
            telegram_proxy=os.getenv("TELEGRAM_PROXY", "").strip() or None,
            database_path=Path(_env_str("DATABASE_PATH", "data/bot.db")),
            downloads_dir=Path(_env_str("DOWNLOADS_DIR", "downloads")),
            log_dir=Path(_env_str("LOG_DIR", "logs")),
            max_concurrent_downloads=max(1, _env_int("MAX_CONCURRENT_DOWNLOADS", 3)),
            max_active_jobs_per_user=max(1, _env_int("MAX_ACTIVE_JOBS_PER_USER", 1)),
            queue_max_size=max(1, _env_int("QUEUE_MAX_SIZE", 50)),
            max_playlist_tracks=max(1, _env_int("MAX_PLAYLIST_TRACKS", 30)),
            download_timeout=max(60, _env_int("DOWNLOAD_TIMEOUT", 1800)),
            rate_limit_seconds=max(0.0, _env_float("RATE_LIMIT_SECONDS", 2.0)),
            telegram_file_limit_mb=min(50, max(1, _env_int("TELEGRAM_FILE_LIMIT_MB", 49))),
            cleanup_max_age_minutes=max(10, _env_int("CLEANUP_MAX_AGE_MINUTES", 120)),
            spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID", "").strip() or None,
            spotify_client_secret=os.getenv("SPOTIFY_CLIENT_SECRET", "").strip() or None,
            audio_providers=_parse_audio_providers(
                os.getenv("SPOTDL_AUDIO_PROVIDERS", "")
            ),
            cookie_file=(
                Path(raw) if (raw := os.getenv("COOKIE_FILE", "").strip()) else None
            ),
            log_level=_env_str("LOG_LEVEL", "INFO").upper(),
        )
