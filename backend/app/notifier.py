"""Optional Telegram notification when an account is created.

Uses the same bot token and admin chat IDs as the bot service. Sends are
fire-and-forget from a background thread: a Telegram outage must never
slow down or fail a registration. Standard library only.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_executor: ThreadPoolExecutor | None = None


def notify_account_created(
    config: Config, display_name: str, send: Callable[[str, int, str], None] | None = None
) -> None:
    """Queue '<Platform> account created: <display name>' to every admin chat.

    No-op when the bot token or admin IDs are not configured. `send` is
    injectable for tests; production uses the thread-pool Telegram sender.
    """
    if not config.telegram_bot_token or not config.telegram_admin_ids:
        return
    if config.platform_name:
        text = f"✅ {config.platform_name} account created: {display_name}"
    else:
        text = f"✅ Account created: {display_name}"
    for chat_id in sorted(config.telegram_admin_ids):
        if send is not None:
            send(config.telegram_bot_token, chat_id, text)
        else:
            _executor_submit(_send, config.telegram_bot_token, chat_id, text)


def _executor_submit(func, *args) -> None:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tg-notify")
    _executor.submit(func, *args)


def _send(token: str, chat_id: int, text: str) -> None:
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - fixed https constant, not user input
        TELEGRAM_API.format(token=token),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            response.read()
    except Exception:  # notification failures are logged, never raised
        logger.warning("Telegram notification to chat %s failed", chat_id, exc_info=True)
