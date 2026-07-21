"""Async SQLite access via aiosqlite.

A single connection is shared across the app; aiosqlite serializes all
operations on its own worker thread, which is plenty for a bot of this size.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from bot.database.models import GlobalStats, User

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    joined_at   TEXT NOT NULL DEFAULT (datetime('now')),
    last_active TEXT,
    is_banned   INTEGER NOT NULL DEFAULT 0,
    bitrate     TEXT NOT NULL DEFAULT '320k',
    downloads   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS downloads (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    url          TEXT NOT NULL,
    content_type TEXT NOT NULL,
    tracks       INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL,
    error        TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_downloads_user ON downloads (user_id);
CREATE INDEX IF NOT EXISTS idx_downloads_created ON downloads (created_at);

CREATE TABLE IF NOT EXISTS track_cache (
    spotify_id TEXT NOT NULL,
    bitrate    TEXT NOT NULL,
    file_id    TEXT NOT NULL,
    title      TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (spotify_id, bitrate)
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None
        # In-memory mirror of banned user ids so the middleware can drop
        # updates from banned users without touching the database at all.
        self._banned_ids: set[int] = set()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database.connect() was never called")
        return self._conn

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()
        async with self._conn.execute(
            "SELECT user_id FROM users WHERE is_banned = 1"
        ) as cur:
            rows = await cur.fetchall()
        self._banned_ids = {row["user_id"] for row in rows}

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ---------------------------------------------------------------- users

    async def upsert_user(
        self, user_id: int, username: str | None, first_name: str | None
    ) -> User:
        """Insert or refresh a user record and return its current state."""
        await self.conn.execute(
            """
            INSERT INTO users (user_id, username, first_name, last_active)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                username    = excluded.username,
                first_name  = excluded.first_name,
                last_active = excluded.last_active
            """,
            (user_id, username, first_name),
        )
        await self.conn.commit()
        user = await self.get_user(user_id)
        assert user is not None
        return user

    async def get_user(self, user_id: int) -> User | None:
        async with self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        return User.from_row(row) if row else None

    def is_banned_cached(self, user_id: int) -> bool:
        """Zero-cost ban check against the in-memory set."""
        return user_id in self._banned_ids

    async def set_banned(self, user_id: int, banned: bool) -> bool:
        """Ban/unban a user. Returns False when the user id is unknown."""
        cur = await self.conn.execute(
            "UPDATE users SET is_banned = ? WHERE user_id = ?",
            (int(banned), user_id),
        )
        await self.conn.commit()
        if cur.rowcount > 0:
            if banned:
                self._banned_ids.add(user_id)
            else:
                self._banned_ids.discard(user_id)
            return True
        return False

    async def set_bitrate(self, user_id: int, bitrate: str) -> None:
        await self.conn.execute(
            "UPDATE users SET bitrate = ? WHERE user_id = ?", (bitrate, user_id)
        )
        await self.conn.commit()

    async def bump_user_downloads(self, user_id: int, by: int) -> None:
        await self.conn.execute(
            "UPDATE users SET downloads = downloads + ? WHERE user_id = ?",
            (by, user_id),
        )
        await self.conn.commit()

    async def get_user_ids(self, include_banned: bool = False) -> list[int]:
        sql = "SELECT user_id FROM users"
        if not include_banned:
            sql += " WHERE is_banned = 0"
        async with self.conn.execute(sql) as cur:
            rows = await cur.fetchall()
        return [row["user_id"] for row in rows]

    # ------------------------------------------------------------ downloads

    async def add_download_record(
        self,
        user_id: int,
        url: str,
        content_type: str,
        tracks: int,
        status: str,
        error: str | None = None,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO downloads (user_id, url, content_type, tracks, status, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, url, content_type, tracks, status, error),
        )
        await self.conn.commit()

    # ---------------------------------------------------------------- cache

    async def get_cached_track(self, spotify_id: str, bitrate: str) -> str | None:
        """Telegram file_id of a previously delivered track, if any."""
        async with self.conn.execute(
            "SELECT file_id FROM track_cache WHERE spotify_id = ? AND bitrate = ?",
            (spotify_id, bitrate),
        ) as cur:
            row = await cur.fetchone()
        return row["file_id"] if row else None

    async def put_cached_track(
        self, spotify_id: str, bitrate: str, file_id: str, title: str | None
    ) -> None:
        await self.conn.execute(
            """
            INSERT OR REPLACE INTO track_cache (spotify_id, bitrate, file_id, title)
            VALUES (?, ?, ?, ?)
            """,
            (spotify_id, bitrate, file_id, title),
        )
        await self.conn.commit()

    async def delete_cached_track(self, spotify_id: str, bitrate: str) -> None:
        await self.conn.execute(
            "DELETE FROM track_cache WHERE spotify_id = ? AND bitrate = ?",
            (spotify_id, bitrate),
        )
        await self.conn.commit()

    # ---------------------------------------------------------------- stats

    async def _scalar(self, sql: str, params: tuple = ()) -> int:
        async with self.conn.execute(sql, params) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    async def global_stats(self) -> GlobalStats:
        return GlobalStats(
            total_users=await self._scalar("SELECT COUNT(*) FROM users"),
            banned_users=await self._scalar(
                "SELECT COUNT(*) FROM users WHERE is_banned = 1"
            ),
            active_24h=await self._scalar(
                "SELECT COUNT(*) FROM users WHERE last_active >= datetime('now', '-1 day')"
            ),
            active_7d=await self._scalar(
                "SELECT COUNT(*) FROM users WHERE last_active >= datetime('now', '-7 days')"
            ),
            total_jobs=await self._scalar("SELECT COUNT(*) FROM downloads"),
            successful_jobs=await self._scalar(
                "SELECT COUNT(*) FROM downloads WHERE status = 'success'"
            ),
            failed_jobs=await self._scalar(
                "SELECT COUNT(*) FROM downloads WHERE status = 'failed'"
            ),
            jobs_today=await self._scalar(
                "SELECT COUNT(*) FROM downloads WHERE created_at >= date('now')"
            ),
            tracks_sent=await self._scalar(
                "SELECT COALESCE(SUM(tracks), 0) FROM downloads"
            ),
        )
