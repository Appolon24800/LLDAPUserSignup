"""Application configuration loaded from environment variables.

Fails fast at startup: any missing or malformed value raises ConfigError so a
misconfigured deployment never serves traffic.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

_RATE_LIMIT_RE = re.compile(r"^\d+\s+per\s+(second|minute|hour|day)$", re.IGNORECASE)
# scheme://host[:port] — no paths, no wildcards.
_ORIGIN_RE = re.compile(r"^https?://[A-Za-z0-9.\-]+(?::\d+)?$")

# Arbitrary floor for generated secrets: 32 chars of base64 ≈ 190 bits.
_MIN_SECRET_LENGTH = 32


class ConfigError(Exception):
    """Raised when the environment configuration is invalid or incomplete."""


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required")
    return value


def _secret(env: Mapping[str, str], name: str) -> str:
    value = _required(env, name)
    if len(value) < _MIN_SECRET_LENGTH:
        raise ConfigError(
            f"{name} must be at least {_MIN_SECRET_LENGTH} characters of random data "
            f"(generate with: python -c \"import secrets; print(secrets.token_urlsafe(32))\")"
        )
    return value


def _int_in_range(
    env: Mapping[str, str], name: str, default: int, minimum: int, maximum: int
) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from None
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}, got {value}")
    return value


def _rate_limit(env: Mapping[str, str], name: str, default: str) -> str:
    raw = env.get(name, "").strip() or default
    if not _RATE_LIMIT_RE.match(raw):
        raise ConfigError(
            f"{name} must look like '20 per minute' (second/minute/hour/day), got {raw!r}"
        )
    return raw


@dataclass(frozen=True)
class Config:
    """Immutable runtime configuration for the backend."""

    base_url: str
    ldap_url: str
    ldap_admin_dn: str
    ldap_admin_password: str
    ldap_base_dn: str
    ldap_allow_insecure: bool
    internal_api_key: str
    flask_secret_key: str
    cors_allowed_origins: tuple[str, ...]
    code_expiry_minutes: int
    max_failed_attempts: int
    rate_limit_validate: str
    rate_limit_submit: str
    database_path: str
    max_upload_mb: int
    proxy_trusted_count: int
    # Optional: shown to users ("<Platform> account created") and used in
    # Telegram registration notifications. Empty = generic wording.
    platform_name: str = ""
    # Optional: when both are set, the backend messages the admin chats on
    # every successful registration (same token/IDs as the bot service).
    telegram_bot_token: str = ""
    telegram_admin_ids: frozenset[int] = frozenset()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        env = os.environ if env is None else env

        base_url = _required(env, "BASE_URL").rstrip("/")
        parsed = urlparse(base_url)
        valid = parsed.scheme in ("http", "https") and parsed.netloc and parsed.path in ("", "/")
        if not valid:
            raise ConfigError(f"BASE_URL must be an absolute http(s) URL, got {base_url!r}")

        ldap_url = _required(env, "LDAP_URL").rstrip("/")
        parsed = urlparse(ldap_url)
        if parsed.scheme not in ("ldap", "ldaps") or not parsed.netloc:
            raise ConfigError(f"LDAP_URL must be an ldap(s)://host:port URL, got {ldap_url!r}")

        raw_origins = env.get("CORS_ALLOWED_ORIGINS", "").strip()
        origins: tuple[str, ...] = ()
        if raw_origins:
            parts = [o.strip() for o in raw_origins.split(",") if o.strip()]
            for origin in parts:
                if origin == "*":
                    raise ConfigError(
                        "CORS_ALLOWED_ORIGINS must not contain '*' in production; "
                        "list explicit origins (or leave empty for same-origin deployments)"
                    )
                if not _ORIGIN_RE.match(origin):
                    raise ConfigError(
                        f"CORS_ALLOWED_ORIGINS contains an invalid origin: {origin!r}"
                    )
            origins = tuple(parts)

        platform_name = env.get("PLATFORM_NAME", "").strip()
        if len(platform_name) > 64 or any(ord(ch) < 32 for ch in platform_name):
            raise ConfigError("PLATFORM_NAME must be 0-64 printable characters")

        raw_notify_ids = env.get("TELEGRAM_ADMIN_IDS", "").strip()
        notify_ids: frozenset[int] = frozenset()
        if raw_notify_ids:
            try:
                notify_ids = frozenset(
                    int(part.strip()) for part in raw_notify_ids.split(",") if part.strip()
                )
            except ValueError:
                raise ConfigError(
                    "TELEGRAM_ADMIN_IDS must be comma-separated numeric Telegram user IDs"
                ) from None

        return cls(
            base_url=base_url,
            ldap_url=ldap_url,
            ldap_admin_dn=_required(env, "LDAP_ADMIN_DN"),
            ldap_admin_password=_required(env, "LDAP_ADMIN_PASSWORD"),
            ldap_base_dn=_required(env, "LDAP_BASE_DN"),
            ldap_allow_insecure=env.get("LDAP_ALLOW_INSECURE", "false").strip().lower()
            in ("1", "true", "yes"),
            internal_api_key=_secret(env, "INTERNAL_API_KEY"),
            flask_secret_key=_secret(env, "FLASK_SECRET_KEY"),
            cors_allowed_origins=origins,
            code_expiry_minutes=_int_in_range(env, "CODE_EXPIRY_MINUTES", 60, 1, 10080),
            max_failed_attempts=_int_in_range(env, "MAX_FAILED_ATTEMPTS", 5, 1, 100),
            rate_limit_validate=_rate_limit(env, "RATE_LIMIT_VALIDATE", "20 per minute"),
            rate_limit_submit=_rate_limit(env, "RATE_LIMIT_SUBMIT", "5 per minute"),
            database_path=_required(env, "DATABASE_PATH"),
            max_upload_mb=_int_in_range(env, "MAX_UPLOAD_MB", 2, 1, 16),
            proxy_trusted_count=_int_in_range(env, "PROXY_TRUSTED_COUNT", 1, 0, 10),
            platform_name=platform_name,
            telegram_bot_token=env.get("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_admin_ids=notify_ids,
        )
