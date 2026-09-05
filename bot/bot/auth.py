"""Admin allow-list and per-user command throttling.

The Telegram side of the authorization model: only TELEGRAM_ADMIN_IDS may
use commands; everyone else gets one generic message (no detail about what
was denied), and every user is throttled regardless of status.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable

NOT_AUTHORIZED_MESSAGE = "⛔ Not authorized."
SLOW_DOWN_MESSAGE = "⏳ Too many commands. Please wait a moment."

MAX_CALLS = 10
WINDOW_SECONDS = 60.0


def is_admin(user_id: int | None, admin_ids: frozenset[int] | set[int]) -> bool:
    return user_id is not None and user_id in admin_ids


class UserRateLimiter:
    """Sliding-window throttle, per user, in-process."""

    def __init__(
        self,
        max_calls: int = MAX_CALLS,
        window_seconds: float = WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.clock = clock
        self._calls: dict[int, deque[float]] = defaultdict(deque)

    def allow(self, user_id: int) -> bool:
        now = self.clock()
        calls = self._calls[user_id]
        while calls and now - calls[0] >= self.window_seconds:
            calls.popleft()
        if len(calls) >= self.max_calls:
            return False
        calls.append(now)
        return True
