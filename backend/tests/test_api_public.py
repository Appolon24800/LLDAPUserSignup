"""Public API: validate-code and register endpoints (LDAP mocked)."""

from __future__ import annotations

import io

from app.limiter import limiter
from tests.conftest import VALID_FORM


def post_json(client, path, payload):
    return client.post(path, json=payload)


def register(client, code, overrides=None, files=None):
    form = {"code": code, **VALID_FORM, **(overrides or {})}
    form.update(files or {})
    return client.post("/api/v1/register", data=form)


# --- validate-code ------------------------------------------------------------


def test_validate_code_ok(client, code):
    res = post_json(client, "/api/v1/validate-code", {"code": code})
    assert res.status_code == 200
    body = res.get_json()
    assert body["valid"] is True
    assert "expires_at" in body


def test_validate_code_unknown(client):
    res = post_json(client, "/api/v1/validate-code", {"code": "garbage"})
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "invalid_code"


def test_validate_code_missing(client):
    res = post_json(client, "/api/v1/validate-code", {})
    assert res.status_code == 400
    assert res.get_json()["error"]["field_errors"]["code"] == "required"


def test_validate_code_non_json(client):
    res = client.post("/api/v1/validate-code", data="not json", content_type="text/plain")
    assert res.status_code == 400


def test_validate_code_after_use(client, fake_ldap, code):
    register(client, code)
    res = post_json(client, "/api/v1/validate-code", {"code": code})
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "code_used"


def test_ip_lockout_after_repeated_bad_codes(client, config):
    for _ in range(config.max_failed_attempts):
        post_json(client, "/api/v1/validate-code", {"code": "wrong"})
    res = post_json(client, "/api/v1/validate-code", {"code": "wrong"})
    assert res.status_code == 429
    assert res.get_json()["error"]["code"] == "ip_locked"
    assert "Retry-After" in res.headers
    # Lockout applies even to a *valid* code from the same IP.
    good = client.application.extensions["code_store"].create(("g",), created_by="x")
    res = post_json(client, "/api/v1/validate-code", {"code": good})
    assert res.status_code == 429


def test_successful_validation_resets_ip_counter(client, code):
    for _ in range(2):  # below lockout threshold
        post_json(client, "/api/v1/validate-code", {"code": "wrong"})
    assert post_json(client, "/api/v1/validate-code", {"code": code}).status_code == 200
    # Counter reset: two more failures still don't lock (threshold is 3).
    for _ in range(2):
        post_json(client, "/api/v1/validate-code", {"code": "wrong"})
    res = post_json(client, "/api/v1/validate-code", {"code": "wrong"})
    assert res.status_code == 400  # not 429


# --- register -------------------------------------------------------------------


def test_register_happy_path(client, fake_ldap, code, monkeypatch):
    from app.api import public

    notifications = []
    monkeypatch.setattr(
        public,
        "notify_account_created",
        lambda cfg, display_name: notifications.append(display_name),
    )
    syncs = []
    monkeypatch.setattr(
        public,
        "trigger_ldap_sync",
        lambda cfg: syncs.append(cfg),
    )
    res = register(client, code)
    assert res.status_code == 201
    assert res.get_json() == {"username": "alice", "created": True}
    created = fake_ldap.created[0]
    assert created["username"] == "alice"
    assert created["first_name"] == "Alice"
    assert created["last_name"] == "Smith"
    assert created["display_name"] == "Alice Smith"
    assert fake_ldap.group_adds == [("alice", ["family"])]
    assert notifications == ["Alice Smith"]  # display name, not username
    assert len(syncs) == 1  # PocketID sync triggered exactly once, with the app config
    # Code is single-use now.
    assert post_json(client, "/api/v1/validate-code", {"code": code}).status_code == 400


def test_register_single_word_name(client, fake_ldap, code):
    res = register(client, code, overrides={"full_name": "Madonna"})
    assert res.status_code == 201
    created = fake_ldap.created[0]
    assert created["first_name"] == "Madonna"
    assert created["last_name"] == "Madonna"
    assert created["display_name"] == "Madonna"


def test_register_multi_word_surname(client, fake_ldap, code):
    res = register(client, code, overrides={"full_name": "Jean Pierre Dupont"})
    assert res.status_code == 201
    created = fake_ldap.created[0]
    assert created["first_name"] == "Jean"
    assert created["last_name"] == "Pierre Dupont"
    assert created["display_name"] == "Jean Pierre Dupont"


def test_register_with_photo(client, fake_ldap, code):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (200, 10, 10)).save(buf, format="PNG")
    buf.seek(0)
    res = register(client, code, files={"photo": (buf, "pic.png", "image/png")})
    assert res.status_code == 201
    photo = fake_ldap.created[0]["photo_jpeg"]
    assert photo.startswith(b"\xff\xd8")


def test_register_invalid_fields(client, code):
    res = register(
        client,
        code,
        overrides={
            "username": "Alice!",
            "full_name": "Alice <script>",
            "email": "nope",
            "password": "short",
        },
    )
    assert res.status_code == 400
    field_errors = res.get_json()["error"]["field_errors"]
    assert field_errors["username"] == "invalid_format"
    assert field_errors["full_name"] == "invalid_format"
    assert field_errors["email"] == "invalid_format"
    assert field_errors["password"] == "too_short"


def test_register_invalid_code_counts_ip_failure(client):
    for _ in range(3):
        register(client, "bogus-code")
    res = register(client, "bogus-code")
    assert res.status_code == 429


def test_register_burns_code_after_max_failures(client, config, code):
    # Each failure also feeds the IP lockout; resetting it between attempts
    # simulates the attack coming from different IPs so the code's own
    # limit is what triggers.
    lockout = client.application.extensions["ip_lockout"]
    for _ in range(config.max_failed_attempts):
        lockout.reset("127.0.0.1")
        res = register(client, code, overrides={"password": "short"})
        assert res.status_code == 400
    lockout.reset("127.0.0.1")
    res = register(client, code)
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "code_locked"


def test_register_username_taken(client, fake_ldap, code):
    fake_ldap.existing_users.add("alice")
    res = register(client, code)
    assert res.status_code == 409
    assert res.get_json()["error"]["code"] == "username_taken"
    # LDAP untouched, code still valid.
    assert fake_ldap.created == []
    assert post_json(client, "/api/v1/validate-code", {"code": code}).status_code == 200


def test_register_ldap_create_failure_reverts_code(client, fake_ldap, code):
    fake_ldap.fail_create = True
    res = register(client, code)
    assert res.status_code == 502
    assert res.get_json()["error"]["code"] == "ldap_error"
    assert post_json(client, "/api/v1/validate-code", {"code": code}).status_code == 200


def test_register_group_failure_deletes_user_and_reverts(client, fake_ldap, code):
    fake_ldap.fail_groups = True
    res = register(client, code)
    assert res.status_code == 502
    assert fake_ldap.deleted == ["alice"]  # half-created user removed
    assert post_json(client, "/api/v1/validate-code", {"code": code}).status_code == 200


def test_register_rejects_bad_photo(client, code):
    res = register(client, code, files={"photo": (io.BytesIO(b"text file"), "x.png", "image/png")})
    assert res.status_code == 400
    assert res.get_json()["error"]["field_errors"]["photo"] == "unsupported"


def test_register_rejects_oversized_request(client, app, code):
    app.config["MAX_CONTENT_LENGTH"] = 1024
    res = register(client, code, overrides={"first_name": "A" * 5000})
    assert res.status_code == 413
    assert res.get_json()["error"]["code"] == "payload_too_large"


def test_register_double_submission_same_code(client, fake_ldap, code):
    assert register(client, code).status_code == 201
    res = register(client, code, overrides={"username": "bob"})
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "code_used"
    assert len(fake_ldap.created) == 1


# --- rate limiting (Flask-Limiter) -------------------------------------------------


def _tighten_limit(client, field, value):
    import dataclasses

    client.get("/healthz")  # ensure limiter storage is initialized
    limiter.reset()
    client.application.config["APP_CONFIG"] = dataclasses.replace(
        client.application.config["APP_CONFIG"], **{field: value}
    )


def test_rate_limit_validate(client, config):
    limiter.enabled = True
    try:
        _tighten_limit(client, "rate_limit_validate", "3 per minute")
        good = client.application.extensions["code_store"].create(("g",), created_by="x")
        for _ in range(3):
            assert post_json(client, "/api/v1/validate-code", {"code": good}).status_code == 200
        res = post_json(client, "/api/v1/validate-code", {"code": good})
        assert res.status_code == 429
        assert res.get_json()["error"]["code"] == "rate_limited"
    finally:
        limiter.reset()


def test_rate_limit_register(client, fake_ldap, code):
    limiter.enabled = True
    try:
        _tighten_limit(client, "rate_limit_submit", "2 per minute")
        assert register(client, "bad-code").status_code == 400
        assert register(client, "bad-code").status_code == 400
        assert register(client, "bad-code").status_code == 429
    finally:
        limiter.reset()
