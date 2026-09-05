"""Per-IP exponential backoff after failed registration-code attempts.

Flask-Limiter (in-memory, per-worker) provides coarse request throttling;
this SQLite-backed lockout is the hard, shared-across-workers boundary:

- first failures are free,
- from BACKOFF_THRESHOLD consecutive failures the IP is locked for
  BACKOFF_BASE_SECONDS * 2**(failures - threshold), capped at one hour,
- a successful code validation resets the counter.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .db import connect

BACKOFF_THRESHOLD = 3
BACKOFF_BASE_SECONDS = 30
BACKOFF_CAP_SECONDS = 3600


def _now() -> datetime:
    return datetime.now(UTC)


def backoff_seconds(failed_attempts: int) -> int:
    """Lockout duration for a given consecutive-failure count (0 when below threshold)."""
    if failed_attempts < BACKOFF_THRESHOLD:
        return 0
    raw = BACKOFF_BASE_SECONDS * 2 ** (failed_attempts - BACKOFF_THRESHOLD)
    return min(raw, BACKOFF_CAP_SECONDS)


class IpLockout:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def locked_for(self, ip: str) -> float:
        """Seconds remaining in the lockout (0.0 when not locked)."""
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT locked_until FROM ip_lockouts WHERE ip = ?", (ip,)
            ).fetchone()
        if row is None or row["locked_until"] is None:
            return 0.0
        remaining = (
            datetime.fromisoformat(row["locked_until"]) - _now()
        ).total_seconds()
        return max(remaining, 0.0)

    def is_locked(self, ip: str) -> bool:
        return self.locked_for(ip) > 0

    def register_failure(self, ip: str) -> int:
        """Record one failed attempt; returns the new consecutive-failure count."""
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO ip_lockouts (ip, failed_attempts, locked_until) "
                "VALUES (?, 1, NULL) "
                "ON CONFLICT(ip) DO UPDATE SET failed_attempts = failed_attempts + 1",
                (ip,),
            )
            row = conn.execute(
                "SELECT failed_attempts FROM ip_lockouts WHERE ip = ?", (ip,)
            ).fetchone()
            attempts = row["failed_attempts"]
            seconds = backoff_seconds(attempts)
            if seconds:
                conn.execute(
                    "UPDATE ip_lockouts SET locked_until = ? WHERE ip = ?",
                    ((_now() + timedelta(seconds=seconds)).isoformat(), ip),
                )
            conn.commit()
        return attempts

    def reset(self, ip: str) -> None:
        with connect(self.db_path) as conn:
            conn.execute("DELETE FROM ip_lockouts WHERE ip = ?", (ip,))
            conn.commit()
