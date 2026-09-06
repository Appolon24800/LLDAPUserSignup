"""Registration code lifecycle: create/validate/expire/consume/revoke/lockout."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.codes import CodeClaimError, CodeStore, _now, _to_iso, hash_code
from app.db import connect, init_db


@pytest.fixture()
def store(tmp_path) -> CodeStore:
    path = str(tmp_path / "codes.db")
    init_db(path)
    return CodeStore(path, max_failed_attempts=3, expiry_minutes=60)


@pytest.fixture()
def code(store) -> str:
    return store.create(("family", "media"), created_by="123456")


def test_create_returns_urlsafe_token(store, code):
    assert len(code) >= 40
    assert code.isalnum() or set(code) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )
    record = store.get(code)
    assert record.groups == ("family", "media")
    assert record.created_by == "123456"
    assert record.code_hint == code[:4] + "…"
    assert record.expires_at > record.created_at


def test_raw_code_not_stored(store, code):
    with connect(store.db_path) as conn:
        rows = conn.execute("SELECT code_hash FROM registration_codes").fetchall()
    assert all(r["code_hash"] == hash_code(code) for r in rows)
    # The token itself must not appear anywhere in the file.
    with open(store.db_path, "rb") as fh:
        assert code.encode() not in fh.read()


def test_no_expiry_codes_never_expire(tmp_path):
    path = str(tmp_path / "codes.db")
    init_db(path)
    store = CodeStore(path, max_failed_attempts=3, expiry_minutes=0)
    code = store.create(("family",), created_by="x")
    record = store.get(code)
    assert record.never_expires is True
    assert store.status(code) == "valid"
    assert store.claim(code, used_by="alice").used_by == "alice"
    assert store.list_active() == []  # claimed -> inactive


def test_tokens_are_unique(store):
    tokens = {store.create((), created_by="x") for _ in range(50)}
    assert len(tokens) == 50


def test_status_valid(store, code):
    assert store.status(code) == "valid"


def test_status_unknown_code(store):
    assert store.status("no-such-code") == "invalid"


def test_claim_marks_used(store, code):
    record = store.claim(code, used_by="alice")
    assert record.used_by == "alice"
    assert record.used_at is not None
    assert store.status(code) == "used"


def test_double_claim_rejected(store, code):
    store.claim(code, used_by="alice")
    with pytest.raises(CodeClaimError) as exc:
        store.claim(code, used_by="bob")
    assert exc.value.status == "used"


def test_expired_code(store, code):
    past = _to_iso(_now() - timedelta(minutes=1))
    with connect(store.db_path) as conn:
        conn.execute(
            "UPDATE registration_codes SET expires_at = ? WHERE code_hash = ?",
            (past, hash_code(code)),
        )
        conn.commit()
    assert store.status(code) == "expired"
    with pytest.raises(CodeClaimError) as exc:
        store.claim(code, used_by="alice")
    assert exc.value.status == "expired"


def test_revoked_code(store, code):
    assert store.revoke(code) is True
    assert store.status(code) == "revoked"
    with pytest.raises(CodeClaimError) as exc:
        store.claim(code, used_by="alice")
    assert exc.value.status == "revoked"


def test_revoke_unknown_code(store):
    assert store.revoke("no-such-code") is False


def test_locked_after_max_failed_attempts(store, code):
    for i in range(3):
        assert store.register_failure(code) == i + 1
    assert store.status(code) == "locked"
    with pytest.raises(CodeClaimError) as exc:
        store.claim(code, used_by="alice")
    assert exc.value.status == "locked"


def test_revert_claim_restores_usability(store, code):
    store.claim(code, used_by="alice")
    store.revert_claim(code, used_by="alice")
    assert store.status(code) == "valid"
    record = store.claim(code, used_by="alice")  # can be claimed again
    assert record.used_by == "alice"


def test_revert_claim_only_for_matching_user(store, code):
    store.claim(code, used_by="alice")
    store.revert_claim(code, used_by="mallory")  # must not revert
    assert store.status(code) == "used"


def test_list_active_excludes_used_revoked_expired(store, code):
    other = store.create(("x",), created_by="123456")
    used = store.create(("y",), created_by="123456")
    revoked = store.create(("z",), created_by="123456")
    store.claim(used, used_by="u")
    store.revoke(revoked)

    active = {r.code_hint for r in store.list_active()}
    assert store.get(code).code_hint in active
    assert store.get(other).code_hint in active
    assert store.get(used).code_hint not in active
    assert store.get(revoked).code_hint not in active


def test_purge_deletes_old_rows(store, tmp_path):
    code2 = store.create((), created_by="x")
    with connect(store.db_path) as conn:
        conn.execute(
            "UPDATE registration_codes SET expires_at = ? WHERE code_hash = ?",
            (_to_iso(store.get(code2).expires_at - timedelta(days=30)), hash_code(code2)),
        )
        conn.commit()
    store.list_active()  # triggers purge
    with connect(store.db_path) as conn:
        remaining = conn.execute("SELECT COUNT(*) AS n FROM registration_codes").fetchone()
    assert remaining["n"] == 0
