"""Per-IP exponential backoff lockout."""

from __future__ import annotations

import pytest

from app.db import init_db
from app.lockout import BACKOFF_CAP_SECONDS, IpLockout, backoff_seconds


@pytest.fixture()
def lockout(tmp_path) -> IpLockout:
    path = str(tmp_path / "lockout.db")
    init_db(path)
    return IpLockout(path)


def test_backoff_curve():
    assert backoff_seconds(0) == 0
    assert backoff_seconds(2) == 0
    assert backoff_seconds(3) == 30
    assert backoff_seconds(4) == 60
    assert backoff_seconds(5) == 120
    assert backoff_seconds(20) == BACKOFF_CAP_SECONDS  # capped at 1h


def test_no_lockout_before_threshold(lockout):
    assert not lockout.is_locked("1.2.3.4")
    lockout.register_failure("1.2.3.4")
    lockout.register_failure("1.2.3.4")
    assert not lockout.is_locked("1.2.3.4")
    assert lockout.locked_for("1.2.3.4") == 0.0


def test_locks_at_third_failure(lockout):
    for _ in range(3):
        lockout.register_failure("1.2.3.4")
    assert lockout.is_locked("1.2.3.4")
    remaining = lockout.locked_for("1.2.3.4")
    assert 0 < remaining <= 30


def test_lockout_escalates(lockout):
    for _ in range(4):
        lockout.register_failure("5.6.7.8")
    assert 30 < lockout.locked_for("5.6.7.8") <= 60


def test_lockout_is_per_ip(lockout):
    for _ in range(3):
        lockout.register_failure("9.9.9.9")
    assert lockout.is_locked("9.9.9.9")
    assert not lockout.is_locked("1.1.1.1")


def test_reset_clears(lockout):
    for _ in range(5):
        lockout.register_failure("1.2.3.4")
    lockout.reset("1.2.3.4")
    assert not lockout.is_locked("1.2.3.4")
    assert lockout.register_failure("1.2.3.4") == 1  # counter restarted


def test_factory_registers_extensions(app):
    assert "code_store" in app.extensions
    assert "ip_lockout" in app.extensions
    store = app.extensions["code_store"]
    assert store.max_failed_attempts == app.config["APP_CONFIG"].max_failed_attempts
