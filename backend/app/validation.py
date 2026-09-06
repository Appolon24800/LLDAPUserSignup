"""Server-side input validation.

Pure functions: each takes a raw value and returns an error code (a short,
stable string the frontend can translate) or None when valid. The frontend
mirrors these rules for live feedback, but the server never trusts the client
and re-validates every submission.
"""

from __future__ import annotations

import math
import re

USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,32}$")
EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$"
)

NAME_MAX_LENGTH = 64
EMAIL_MAX_LENGTH = 254

PASSWORD_MIN_LENGTH = 12
PASSWORD_MIN_ENTROPY_BITS = 60

# Lowercase. Usernames that commonly collide with system/service accounts.
RESERVED_USERNAMES = frozenset(
    {
        "admin",
        "administrator",
        "root",
        "system",
        "postmaster",
        "hostmaster",
        "webmaster",
        "abuse",
        "support",
        "help",
        "info",
        "mail",
        "mailer-daemon",
        "news",
        "www",
        "ldap",
        "ldapadmin",
        "lldap",
        "auth",
        "authadmin",
        "security",
        "sysadmin",
        "operator",
        "guest",
        "anonymous",
        "service",
        "api",
        "backup",
        "nobody",
        "daemon",
    }
)

# Small embedded denylist (lowercase) — catches the most common choices that
# pass naive length/entropy checks. Not a substitute for entropy, a supplement.
COMMON_PASSWORDS = frozenset(
    {
        "password", "password1", "password123", "passw0rd", "p@ssw0rd",
        "123456", "1234567", "12345678", "123456789", "1234567890",
        "qwerty", "qwerty123", "qwertyuiop", "azerty", "azerty123",
        "abc123", "abcd1234", "iloveyou", "princess", "monkey", "dragon",
        "letmein", "welcome", "welcome1", "admin", "admin123", "master",
        "sunshine", "football", "baseball", "shadow", "michael", "jennifer",
        "trustno1", "hunter2", "superman", "batman", "starwars", "pokemon",
        "whatever", "secret", "changeme", "hello123", "test123",
        "soleil", "marseille", "doudou", "loulou", "chouchou", "lapin",
        "motdepasse", "bonjour", "carotte", "chocolat", "trotro",
        "azertyuiop", "qsdfghjklm", "wxcvbn",
    }
)


def _has_control_chars(value: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def validate_username(value: object) -> str | None:
    if not isinstance(value, str):
        return "invalid_type"
    if _has_control_chars(value):
        return "invalid_format"
    if not USERNAME_RE.fullmatch(value):
        return "invalid_format"
    if value.lower() in RESERVED_USERNAMES:
        return "reserved"
    return None


def validate_name(value: object) -> str | None:
    """Human names (full name): unicode letters, spaces, - and '."""
    if not isinstance(value, str):
        return "invalid_type"
    stripped = value.strip()
    if not 1 <= len(stripped) <= NAME_MAX_LENGTH:
        return "invalid_length"
    if _has_control_chars(stripped):
        return "invalid_format"
    if any(not (ch.isalpha() or ch in " -'") for ch in stripped):
        return "invalid_format"
    if not any(ch.isalpha() for ch in stripped):
        return "invalid_format"
    return None


def split_full_name(full_name: str) -> tuple[str, str]:
    """Derive (first_name, last_name) for LDAP from a single full-name string.

    First word becomes the given name, the rest the surname; single-word
    names are used for both so `sn` (required by inetOrgPerson) stays filled.
    The display name is always the full string exactly as typed.
    """
    parts = full_name.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], " ".join(parts[1:])


def validate_email(value: object) -> str | None:
    if not isinstance(value, str):
        return "invalid_type"
    stripped = value.strip()
    if not stripped or len(stripped) > EMAIL_MAX_LENGTH:
        return "invalid_length"
    if _has_control_chars(stripped):
        return "invalid_format"
    if not EMAIL_RE.fullmatch(stripped):
        return "invalid_format"
    local = stripped.rsplit("@", 1)[0]
    if local.startswith(".") or local.endswith(".") or ".." in local:
        return "invalid_format"
    return None


def password_entropy_bits(value: str) -> float:
    """Pool-based entropy estimate with a repeat cap.

    Natural language repeats characters, so scoring only unique characters
    punishes real passphrases ("anticonstitutionnellement" would score like
    an 11-character password). The effective length is the actual length
    capped at 2.5x the unique-character count: normal words keep most of
    their length credit while degenerate repetition ("aaaa", "abcabc")
    collapses. The pool is the sum of the character-class sizes observed.
    """
    pool = 0
    if any(ch.islower() for ch in value):
        pool += 26
    if any(ch.isupper() for ch in value):
        pool += 26
    if any(ch.isdigit() for ch in value):
        pool += 10
    if any(not ch.isalnum() for ch in value):
        pool += 33
    if pool == 0:
        return 0.0
    effective_length = min(len(value), 2.5 * len(set(value)))
    return effective_length * math.log2(pool)


def validate_password(value: object) -> str | None:
    if not isinstance(value, str):
        return "invalid_type"
    if len(value) < PASSWORD_MIN_LENGTH:
        return "too_short"
    if _has_control_chars(value):
        return "invalid_format"
    # Substring match: "password12345" contains "password"; suffixes and
    # decorations around a common word stay common.
    lowered = value.lower()
    if any(common in lowered for common in COMMON_PASSWORDS):
        return "too_common"
    if password_entropy_bits(value) < PASSWORD_MIN_ENTROPY_BITS:
        return "too_weak"
    return None


def validate_password_confirm(password: object, confirm: object) -> str | None:
    if not isinstance(confirm, str):
        return "invalid_type"
    return None if password == confirm else "mismatch"
