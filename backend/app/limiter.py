"""Shared Flask-Limiter extension instance.

Limits are declared per-endpoint with config-driven strings
(RATE_LIMIT_VALIDATE / RATE_LIMIT_SUBMIT) at blueprint registration time.
Storage is per-worker memory (documented approximation); the hard,
cross-worker protection is the SQLite-backed IP lockout in app.lockout.
"""

from __future__ import annotations

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",
)
