"""Logging setup: console + rotating file logs + a dedicated error log."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from bot.config import Config

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def setup_logging(config: Config) -> None:
    """Configure the root logger. Safe to call exactly once at startup."""
    config.log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(config.log_level)
    formatter = logging.Formatter(_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        config.log_dir / "bot.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Errors additionally land in their own file so /admin can surface them.
    error_handler = RotatingFileHandler(
        config.error_log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root.addHandler(error_handler)
