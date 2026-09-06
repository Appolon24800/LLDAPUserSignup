"""Internal bot API: authentication, code generation, listing, revocation."""

from __future__ import annotations

from tests.conftest import SECRET, Group

AUTH = {"X-Internal-API-Key": SECRET}


def test_unauthenticated_requests_rejected(client):
    for method, path in (
        ("post", "/internal/codes"),
        ("get", "/internal/codes"),
        ("post", "/internal/revoke"),
        ("get", "/internal/groups"),
    ):
        res = getattr(client, method)(path, json={} if method == "post" else None)
        assert res.status_code == 401, (method, path)
        assert res.get_json()["error"]["code"] == "unauthorized"


def test_wrong_key_rejected(client):
    wrong = "z" * 40  # distinct from the conftest secret
    assert wrong != SECRET
    res = client.get("/internal/groups", headers={"X-Internal-API-Key": wrong})
    assert res.status_code == 401


def test_create_code_happy_path(client, fake_ldap, config):
    fake_ldap.available_groups = ["family", "media", "admin"]

    res = client.post(
        "/internal/codes",
        headers=AUTH,
        json={"groups": ["media", "family"], "created_by": "123456"},
    )
    assert res.status_code == 201
    body = res.get_json()
    assert body["groups"] == ["family", "media"]  # sorted, deduplicated
    assert body["url"] == f"{config.base_url}/register?code={body['code']}"
    assert "expires_at" in body

    # The generated code is immediately usable on the public endpoint.
    val = client.post("/api/v1/validate-code", json={"code": body["code"]})
    assert val.status_code == 200


def test_create_code_rejects_unknown_groups(client, fake_ldap):
    fake_ldap.available_groups = ["family"]

    res = client.post(
        "/internal/codes", headers=AUTH, json={"groups": ["hackers"], "created_by": "1"}
    )
    assert res.status_code == 400
    assert res.get_json()["error"]["field_errors"]["groups"] == "unknown"


def test_create_code_rejects_bad_payloads(client, fake_ldap):
    fake_ldap.available_groups = ["family"]
    cases = [
        {"groups": [], "created_by": "1"},
        {"groups": "family", "created_by": "1"},
        {"groups": ["family"], "created_by": ""},
        {"groups": ["<script>"], "created_by": "1"},
        {"groups": [f"g{i}" for i in range(25)], "created_by": "1"},
        {},
    ]
    for payload in cases:
        res = client.post("/internal/codes", headers=AUTH, json=payload)
        assert res.status_code == 400, payload


def test_create_code_ldap_down(client, fake_ldap):
    from app.ldap_service import LdapServiceError

    def boom():
        raise LdapServiceError("down")

    fake_ldap.list_groups = boom
    res = client.post(
        "/internal/codes", headers=AUTH, json={"groups": ["family"], "created_by": "1"}
    )
    assert res.status_code == 502
    assert res.get_json()["error"]["code"] == "ldap_error"


def test_list_codes_shape(client, fake_ldap, config):
    fake_ldap.available_groups = ["family", "media"]
    for groups in (["family"], ["media", "family"]):
        res = client.post(
            "/internal/codes", headers=AUTH, json={"groups": groups, "created_by": "42"}
        )
        assert res.status_code == 201

    res = client.get("/internal/codes", headers=AUTH)
    assert res.status_code == 200
    codes = res.get_json()["codes"]
    assert len(codes) == 2
    assert all("code_hint" in c and "expires_at" in c for c in codes)
    assert all("code" not in c for c in codes)  # never returns raw codes


def test_create_code_without_expiry_reports_null(tmp_path):
    from app import create_app
    from tests.conftest import FakeLdap, make_config

    app = create_app(make_config(tmp_path, code_expiry_minutes=0))
    app.extensions["ldap_service"] = FakeLdap(available_groups=["family"])

    res = app.test_client().post(
        "/internal/codes", headers=AUTH, json={"groups": ["family"], "created_by": "1"}
    )
    assert res.status_code == 201
    assert res.get_json()["expires_at"] is None

    listed = app.test_client().get("/internal/codes", headers=AUTH).get_json()["codes"]
    assert listed[0]["expires_at"] is None


def test_revoke_code(client, fake_ldap):
    fake_ldap.available_groups = ["family"]
    code = client.post(
        "/internal/codes", headers=AUTH, json={"groups": ["family"], "created_by": "1"}
    ).get_json()["code"]

    res = client.post("/internal/revoke", headers=AUTH, json={"code": code})
    assert res.status_code == 200
    assert res.get_json()["revoked"] is True

    val = client.post("/api/v1/validate-code", json={"code": code})
    assert val.status_code == 400
    assert val.get_json()["error"]["code"] == "code_revoked"

    # Revoking again reports False (already revoked).
    res = client.post("/internal/revoke", headers=AUTH, json={"code": code})
    assert res.get_json()["revoked"] is False


def test_groups_endpoint(client, fake_ldap):
    fake_ldap.list_groups = lambda: [Group("family", 4), Group("admin", 1)]
    res = client.get("/internal/groups", headers=AUTH)
    assert res.status_code == 200
    assert res.get_json() == {
        "groups": [{"name": "family", "members": 4}, {"name": "admin", "members": 1}]
    }
