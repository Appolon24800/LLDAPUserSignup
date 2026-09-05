"""SQLite access layer.

One short-lived connection per operation: threadsafe by construction and good
enough for this workload. WAL mode allows concurrent readers with a single
writer, and a busy timeout absorbs rare write contention between gunicorn
workers.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS registration_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code_hash TEXT NOT NULL UNIQUE,
    code_hint TEXT NOT NULL,
    groups_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    used_by TEXT,
    revoked_at TEXT,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    last_failed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_codes_expires ON registration_codes (expires_at);

CREATE TABLE IF NOT EXISTS ip_lockouts (
    ip TEXT PRIMARY KEY,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT
);
"""


def init_db(path: str) -> None:
    """Create the schema if it does not exist yet."""
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


@contextmanager
def connect(path: str) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        yield conn
    finally:
        conn.close()
