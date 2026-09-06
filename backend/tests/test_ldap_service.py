"""LdapService operations against ldap3's MOCK_SYNC strategy (no server)."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from ldap3 import MOCK_SYNC, Connection, Server

from app.ldap_service import (
    LdapService,
    UserAlreadyExistsError,
)

BASE = "dc=example,dc=com"
ADMIN_DN = f"uid=admin,ou=people,{BASE}"


def make_service(seeded_groups=(), existing_users=()):
    """Build a LdapService backed by a fresh mock connection factory."""
    server = Server("mockserver")

    @contextmanager
    def factory():
        conn = Connection(
            server,
            user=ADMIN_DN,
            password="pw",
            client_strategy=MOCK_SYNC,
        )
        conn.bind()
        conn.strategy.add_entry(
            ADMIN_DN,
            {"objectClass": ["inetOrgPerson"], "uid": "admin", "cn": "Admin"},
        )
        for group in seeded_groups:
            conn.strategy.add_entry(
                f"cn={group},ou=groups,{BASE}",
                {"objectClass": ["groupOfNames"], "cn": group, "member": []},
            )
        for uid in existing_users:
            conn.strategy.add_entry(
                f"uid={uid},ou=people,{BASE}",
                {"objectClass": ["inetOrgPerson"], "uid": uid, "cn": uid.title()},
            )
        try:
            yield conn
        finally:
            conn.unbind()

    return LdapService(
        url="ldaps://mock:636",
        admin_dn=ADMIN_DN,
        admin_password="pw",
        base_dn=BASE,
        connection_factory=factory,
    )


def test_user_exists_false_then_true():
    svc = make_service()
    assert svc.user_exists("alice") is False
    svc.create_user(
        "alice",
        password="pw",
        first_name="Alice",
        last_name="Smith",
        display_name="Alice Smith",
        email="alice@example.com",
    )
    assert svc.user_exists("alice") is True


def test_create_user_attributes_present():
    svc = make_service()
    svc.create_user(
        "bob",
        password="secret-pw",
        first_name="Bob",
        last_name="Martin",
        display_name="Bob Martin",
        email="bob@example.com",
        photo_jpeg=b"\xff\xd8\xff\xe0fakejpeg",
    )
    with svc._connection_factory() as conn:
        conn.search(
            f"uid=bob,ou=people,{BASE}", "(objectClass=*)", attributes=["*"]
        )
        entry = conn.entries[0]
        assert entry.objectClass.value == "inetOrgPerson"
        assert entry.cn.value == "Bob Martin"
        assert entry.sn.value == "Martin"
        assert entry.givenName.value == "Bob"
        assert entry.mail.value == "bob@example.com"
        assert entry.userPassword.value == "secret-pw"
        assert entry.jpegPhoto.raw_values[0] == b"\xff\xd8\xff\xe0fakejpeg"


def test_create_duplicate_user_raises():
    svc = make_service(existing_users=("carol",))
    with pytest.raises(UserAlreadyExistsError):
        svc.create_user(
            "carol",
            password="pw",
            first_name="C",
            last_name="D",
            display_name="C D",
            email="c@example.com",
        )


def test_add_to_groups():
    svc = make_service(seeded_groups=("family", "media"))
    svc.create_user(
        "dave",
        password="pw",
        first_name="Dave",
        last_name="Brown",
        display_name="Dave Brown",
        email="dave@example.com",
    )
    svc.add_to_groups("dave", ["family", "media"])
    with svc._connection_factory() as conn:
        conn.search(
            f"cn=family,ou=groups,{BASE}", "(objectClass=*)", attributes=["member"]
        )
        members = conn.entries[0].member.values
        assert f"uid=dave,ou=people,{BASE}" in [str(m) for m in members]


def test_list_groups_ordered_by_member_count():
    people = f"ou=people,{BASE}"

    def members(*uids):
        return [f"uid={u},{people}" for u in uids]

    svc = make_service()
    with svc._connection_factory() as conn:
        conn.strategy.add_entry(
            f"cn=lonely,ou=groups,{BASE}",
            {"objectClass": ["groupOfNames"], "cn": "lonely", "member": members("a")},
        )
        conn.strategy.add_entry(
            f"cn=big,ou=groups,{BASE}",
            {"objectClass": ["groupOfNames"], "cn": "big", "member": members("a", "b", "c")},
        )
        conn.strategy.add_entry(
            f"cn=empty,ou=groups,{BASE}",
            {"objectClass": ["groupOfNames"], "cn": "empty", "member": []},
        )
        conn.strategy.add_entry(
            f"cn=also-big,ou=groups,{BASE}",
            {"objectClass": ["groupOfNames"], "cn": "also-big", "member": members("a", "b", "c")},
        )

    groups = svc.list_groups()
    assert [(g.name, g.members) for g in groups] == [
        ("also-big", 3),
        ("big", 3),
        ("lonely", 1),
        ("empty", 0),
    ]


def test_tls_wiring_uses_ca_cert(monkeypatch, tmp_path):
    """The CA path flows into ldap3's Tls as ca_certs_file."""
    import ssl

    captured = {}

    class StopBuild(Exception):
        pass

    class FakeTls:
        def __init__(self, **kwargs):
            captured["tls_kwargs"] = kwargs

    class FakeServer:
        def __init__(self, *args, **kwargs):
            captured["server_kwargs"] = kwargs
            raise StopBuild

    import app.ldap_service as svc_module

    monkeypatch.setattr(svc_module, "Tls", FakeTls)
    monkeypatch.setattr(svc_module, "Server", FakeServer)

    def build(ca_cert=""):
        svc = LdapService(
            url="ldaps://lldap:636",
            admin_dn="uid=admin,dc=x",
            admin_password="pw",
            base_dn="dc=x",
            allow_insecure=False,
            ca_cert=ca_cert,
        )
        with pytest.raises(StopBuild):
            with svc._default_connection():
                pass

    build()
    assert captured["tls_kwargs"] == {"validate": ssl.CERT_REQUIRED}

    build(ca_cert=str(tmp_path / "ca.pem"))
    assert captured["tls_kwargs"] == {
        "validate": ssl.CERT_REQUIRED,
        "ca_certs_file": str(tmp_path / "ca.pem"),
    }


def test_dn_helpers():
    svc = make_service()
    assert svc.user_dn("alice") == f"uid=alice,ou=people,{BASE}"
    assert svc.group_dn("family") == f"cn=family,ou=groups,{BASE}"
