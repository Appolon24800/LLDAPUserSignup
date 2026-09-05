"""Registration code lifecycle over SQLite.

Codes are 256-bit ``secrets.token_urlsafe`` values. Only their SHA-256 hash is
stored, so a leaked database does not leak usable codes. Every state
transition is a single conditional SQL statement so concurrent workers cannot
double-use a code.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .db import connect

CODE_TOKEN_BYTES = 32  # 256-bit token -> ~43 url-safe characters


def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass(frozen=True)
class CodeRecord:
    code_hash: str
    code_hint: str
    groups: tuple[str, ...]
    created_by: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None
    used_by: str | None = None
    revoked_at: datetime | None = None
    failed_attempts: int = 0
    last_failed_at: datetime | None = None


class CodeClaimError(Exception):
    """Raised when a code cannot be claimed; `.status` says why."""

    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


def _row_to_record(row: sqlite3.Row) -> CodeRecord:
    return CodeRecord(
        code_hash=row["code_hash"],
        code_hint=row["code_hint"],
        groups=tuple(json.loads(row["groups_json"])),
        created_by=row["created_by"],
        created_at=_from_iso(row["created_at"]),
        expires_at=_from_iso(row["expires_at"]),
        used_at=_from_iso(row["used_at"]) if row["used_at"] else None,
        used_by=row["used_by"],
        revoked_at=_from_iso(row["revoked_at"]) if row["revoked_at"] else None,
        failed_attempts=row["failed_attempts"],
        last_failed_at=_from_iso(row["last_failed_at"]) if row["last_failed_at"] else None,
    )


class CodeStore:
    def __init__(self, db_path: str, max_failed_attempts: int, expiry_minutes: int) -> None:
        self.db_path = db_path
        self.max_failed_attempts = max_failed_attempts
        self.expiry_minutes = expiry_minutes

    # -- creation -----------------------------------------------------------

    def create(self, groups: tuple[str, ...] | list[str], created_by: str) -> str:
        """Generate, persist and return a fresh single-use code token."""
        token = secrets.token_urlsafe(CODE_TOKEN_BYTES)
        now = _now()
        expires = now + timedelta(minutes=self.expiry_minutes)
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO registration_codes "
                "(code_hash, code_hint, groups_json, created_by, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    hash_code(token),
                    token[:4] + "…",
                    json.dumps(sorted(groups)),
                    created_by,
                    _to_iso(now),
                    _to_iso(expires),
                ),
            )
            conn.commit()
        return token

    # -- inspection ----------------------------------------------------------

    def get(self, token: str) -> CodeRecord | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM registration_codes WHERE code_hash = ?", (hash_code(token),)
            ).fetchone()
        return _row_to_record(row) if row else None

    def status(self, token: str) -> str:
        """One of: valid, invalid, expired, used, revoked, locked."""
        record = self.get(token)
        if record is None:
            return "invalid"
        if record.revoked_at is not None:
            return "revoked"
        if record.used_at is not None:
            return "used"
        if record.expires_at <= _now():
            return "expired"
        if record.failed_attempts >= self.max_failed_attempts:
            return "locked"
        return "valid"

    def list_active(self, limit: int = 50) -> list[CodeRecord]:
        """Unused, unrevoked, unexpired codes, newest first."""
        self._purge_old()
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM registration_codes "
                "WHERE used_at IS NULL AND revoked_at IS NULL AND expires_at > ? "
                "ORDER BY created_at DESC LIMIT ?",
                (_to_iso(_now()), limit),
            ).fetchall()
        return [_row_to_record(r) for r in rows]

    # -- state transitions ----------------------------------------------------

    def claim(self, token: str, used_by: str) -> CodeRecord:
        """Atomically mark a code as used; raise CodeClaimError otherwise."""
        now = _to_iso(_now())
        with connect(self.db_path) as conn:
            cur = conn.execute(
                "UPDATE registration_codes SET used_at = ?, used_by = ? "
                "WHERE code_hash = ? AND used_at IS NULL AND revoked_at IS NULL "
                "AND expires_at > ? AND failed_attempts < ?",
                (now, used_by, hash_code(token), now, self.max_failed_attempts),
            )
            conn.commit()
            if cur.rowcount != 1:
                raise CodeClaimError(self.status(token))
        record = self.get(token)
        if record is None:  # unreachable: claim only succeeds on an existing row
            raise CodeClaimError("invalid")
        return record

    def revert_claim(self, token: str, used_by: str) -> None:
        """Undo a claim after a failed downstream operation (e.g. LDAP error).

        Only reverts when the row is still marked used by the same registrant,
        so it can never erase a different, later successful use.
        """
        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE registration_codes SET used_at = NULL, used_by = NULL "
                "WHERE code_hash = ? AND used_at IS NOT NULL AND used_by = ?",
                (hash_code(token), used_by),
            )
            conn.commit()

    def register_failure(self, token: str) -> int:
        """Count a failed submission attempt; returns the new count."""
        now = _to_iso(_now())
        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE registration_codes "
                "SET failed_attempts = failed_attempts + 1, last_failed_at = ? "
                "WHERE code_hash = ?",
                (now, hash_code(token)),
            )
            conn.commit()
        record = self.get(token)
        return record.failed_attempts if record else 0

    def revoke(self, token: str) -> bool:
        """Invalidate immediately; returns False if the code does not exist."""
        with connect(self.db_path) as conn:
            cur = conn.execute(
                "UPDATE registration_codes SET revoked_at = ? "
                "WHERE code_hash = ? AND revoked_at IS NULL",
                (_to_iso(_now()), hash_code(token)),
            )
            conn.commit()
            return cur.rowcount == 1

    # -- housekeeping ----------------------------------------------------------

    def _purge_old(self, days: int = 7) -> None:
        cutoff = _to_iso(_now() - timedelta(days=days))
        with connect(self.db_path) as conn:
            conn.execute("DELETE FROM registration_codes WHERE expires_at < ?", (cutoff,))
            conn.commit()
