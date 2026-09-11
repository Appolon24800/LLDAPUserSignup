"""Optional PocketID LDAP sync trigger when an account is created.

PocketID (with LDAP enabled) imports LDAP users on startup and hourly only;
without a nudge, a freshly registered user cannot log in via PocketID for up
to an hour. When POCKETID_URL and POCKETID_API_KEY are configured, the
backend asks PocketID to re-sync right after a successful registration:
POST {url}/api/application-configuration/sync-ldap authenticated with an
admin API key (X-API-Key header). Fire-and-forget from a background thread —
a PocketID outage must never slow down or fail a registration, and the
hourly scheduled sync remains the natural fallback. Standard library only.
"""

from __future__ import annotations

import logging
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config

logger = logging.getLogger(__name__)

SYNC_PATH = "/api/application-configuration/sync-ldap"
TIMEOUT_SECONDS = 10

_executor: ThreadPoolExecutor | None = None


def trigger_ldap_sync(config: Config, send: Callable[[str, str], None] | None = None) -> None:
    """Ask PocketID to re-sync its LDAP users (no-op when unconfigured).

    `send` is injectable for tests; production uses the thread-pool sender.
    """
    if not config.pocketid_url or not config.pocketid_api_key:
        return
    if send is not None:
        send(config.pocketid_url, config.pocketid_api_key)
    else:
        _executor_submit(_send, config.pocketid_url, config.pocketid_api_key)


def _executor_submit(func, *args) -> None:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pocketid-sync")
    _executor.submit(func, *args)


def _send(url: str, api_key: str) -> None:
    try:
        request = urllib.request.Request(  # noqa: S310 - operator-configured URL
            f"{url}{SYNC_PATH}",
            headers={"X-API-Key": api_key},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            response.read()
    except Exception:  # sync failures are logged, never raised
        logger.warning("PocketID LDAP sync trigger to %s failed", url, exc_info=True)
