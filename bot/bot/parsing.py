"""Command argument parsing (pure functions, easy to test)."""

from __future__ import annotations

import re

MAX_ARGS = 20


def parse_group_args(text: str | None) -> list[str]:
    """Split a /gen argument string into unique group names.

    Accepts comma- or space-separated lists ('family, media' == 'family media').
    Returns [] when nothing usable was provided.
    """
    if not text or not text.strip():
        return []
    parts = re.split(r"[,\s]+", text.strip())
    names: list[str] = []
    seen: set[str] = set()
    for part in parts:
        name = part.strip().strip("*_`").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
        if len(names) >= MAX_ARGS:
            break
    return names


def parse_revoke_arg(text: str | None) -> str | None:
    """Extract the single registration code from a /revoke argument string."""
    if not text:
        return None
    args = parse_group_args(text)
    if not args:
        return None
    return args[0]


def split_command(text: str | None) -> tuple[str, str]:
    """Split '/gen family,media' into ('/gen', 'family,media').

    Handles /command@BotName forms. Returns the command lowercased and the
    raw remainder.
    """
    if not text or not text.startswith("/"):
        return "", ""
    parts = text.split(maxsplit=1)
    command = parts[0].split("@", 1)[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    return command, rest
