"""Shared fixtures: a valid Config against a temp SQLite file, app, and client."""

from __future__ import annotations

import pytest

from app.config import Config
from app.ldap_service import Group, LdapServiceError, UserAlreadyExistsError

SECRET = "x" * 40  # meets the minimum length check; test-only


class FakeLdap:
    """In-memory LdapService double recording every call."""

    def __init__(self, existing_users=(), available_groups=("family",), fail_create=False,
                 fail_groups=False):
        self.existing_users = set(existing_users)
        self.available_groups = list(available_groups)
        self.fail_create = fail_create
        self.fail_groups = fail_groups
        self.created: list[dict] = []
        self.deleted: list[str] = []
        self.group_adds: list[tuple[str, list[str]]] = []

    def list_groups(self):
        return [Group(name, 0) for name in sorted(self.available_groups)]

    def user_exists(self, username):
        return username in self.existing_users

    def create_user(self, **kwargs):
        if self.fail_create:
            raise LdapServiceError("boom")
        if kwargs["username"] in self.existing_users:
            raise UserAlreadyExistsError(kwargs["username"])
        self.existing_users.add(kwargs["username"])
        self.created.append(kwargs)

    def delete_user(self, username):
        self.existing_users.discard(username)
        self.deleted.append(username)

    def add_to_groups(self, username, groups):
        if self.fail_groups:
            raise LdapServiceError("boom")
        self.group_adds.append((username, list(groups)))


def make_config(tmp_path, **overrides) -> Config:
    defaults = dict(
        base_url="https://signup.example.com",
        ldap_url="ldaps://lldap.example.com:6360",
        ldap_admin_dn="uid=admin,ou=people,dc=example,dc=com",
        ldap_admin_password="admin-password",
        ldap_base_dn="dc=example,dc=com",
        ldap_allow_insecure=False,
        internal_api_key=SECRET,
        flask_secret_key=SECRET,
        cors_allowed_origins=("https://signup.example.com",),
        code_expiry_minutes=60,
        max_failed_attempts=5,
        rate_limit_validate="100000 per hour",
        rate_limit_submit="100000 per hour",
        database_path=str(tmp_path / "test.db"),
        max_upload_mb=2,
        proxy_trusted_count=1,
    )
    defaults.update(overrides)
    return Config(**defaults)


@pytest.fixture()
def config(tmp_path) -> Config:
    return make_config(tmp_path)


@pytest.fixture()
def app(config):
    from app import create_app

    return create_app(config)


@pytest.fixture()
def fake_ldap(app):
    ldap = FakeLdap()
    app.extensions["ldap_service"] = ldap
    return ldap


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _limiter_isolated():
    """Reset the shared limiter storage between tests.

    Limits stay enabled (as in production) but conftest config uses huge
    values so suites never trip them; dedicated rate-limit tests tighten the
    limits per-app via APP_CONFIG (evaluated per request).
    """
    from contextlib import suppress

    from app.limiter import limiter

    with suppress(Exception):  # storage not initialized before any init_app
        limiter.reset()
    yield
    with suppress(Exception):
        limiter.reset()


@pytest.fixture()
def code(app):
    return app.extensions["code_store"].create(("family",), created_by="123")


VALID_FORM = {
    "username": "alice",
    "full_name": "Alice Smith",
    "email": "alice@example.com",
    "password": "Phrase-Harbor7-Velvet",
}
