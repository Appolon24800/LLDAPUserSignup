"""Shared fixtures: a valid Config against a temp SQLite file, app, and client."""

from __future__ import annotations

import pytest

from app.config import Config

SECRET = "x" * 40  # meets the minimum length check; test-only


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
        rate_limit_validate="20 per minute",
        rate_limit_submit="5 per minute",
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
def client(app):
    return app.test_client()
