"""Bot configuration loaded from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

_MIN_SECRET_LENGTH = 32


class BotConfigError(Exception):
    """Raised when the bot environment configuration is invalid."""


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise BotConfigError(f"{name} is required")
    return value


def _url(env: Mapping[str, str], name: str) -> str:
    value = _required(env, name).rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise BotConfigError(f"{name} must be an absolute http(s) URL, got {value!r}")
    return value


@dataclass(frozen=True)
class BotConfig:
    telegram_bot_token: str
    admin_ids: frozenset[int]
    backend_url: str
    internal_api_key: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> BotConfig:
        env = os.environ if env is None else env

        raw_admins = _required(env, "TELEGRAM_ADMIN_IDS")
        try:
            admin_ids = frozenset(
                int(part.strip()) for part in raw_admins.split(",") if part.strip()
            )
        except ValueError:
            raise BotConfigError(
                "TELEGRAM_ADMIN_IDS must be comma-separated numeric Telegram user IDs"
            ) from None
        if not admin_ids:
            raise BotConfigError("TELEGRAM_ADMIN_IDS must contain at least one user ID")

        internal_api_key = _required(env, "INTERNAL_API_KEY")
        if len(internal_api_key) < _MIN_SECRET_LENGTH:
            raise BotConfigError(
                f"INTERNAL_API_KEY must be at least {_MIN_SECRET_LENGTH} characters"
            )

        return cls(
            telegram_bot_token=_required(env, "TELEGRAM_BOT_TOKEN"),
            admin_ids=admin_ids,
            backend_url=_url(env, "BACKEND_URL"),
            internal_api_key=internal_api_key,
        )
