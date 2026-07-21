"""Typed views over database rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class User:
    user_id: int
    username: str | None
    first_name: str | None
    joined_at: str
    last_active: str | None
    is_banned: bool
    bitrate: str
    downloads: int

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> User:
        return cls(
            user_id=row["user_id"],
            username=row["username"],
            first_name=row["first_name"],
            joined_at=row["joined_at"],
            last_active=row["last_active"],
            is_banned=bool(row["is_banned"]),
            bitrate=row["bitrate"],
            downloads=row["downloads"],
        )


@dataclass(frozen=True, slots=True)
class GlobalStats:
    total_users: int
    banned_users: int
    active_24h: int
    active_7d: int
    total_jobs: int
    successful_jobs: int
    failed_jobs: int
    jobs_today: int
    tracks_sent: int
