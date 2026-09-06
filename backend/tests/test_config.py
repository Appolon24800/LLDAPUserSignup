"""Config loading and validation."""

from __future__ import annotations

import pytest

from app.config import Config, ConfigError
from tests.conftest import SECRET

ENV = {
    "BASE_URL": "https://signup.example.com",
    "LDAP_URL": "ldaps://lldap.example.com:6360",
    "LDAP_ADMIN_DN": "uid=admin,ou=people,dc=example,dc=com",
    "LDAP_ADMIN_PASSWORD": "pw",
    "LDAP_BASE_DN": "dc=example,dc=com",
    "DATABASE_PATH": "/var/lib/app/x.db",
    "INTERNAL_API_KEY": SECRET,
    "FLASK_SECRET_KEY": SECRET,
}


def test_from_env_minimal():
    cfg = Config.from_env(ENV)
    assert cfg.base_url == "https://signup.example.com"
    assert cfg.code_expiry_minutes == 0  # no expiry by default
    assert cfg.max_failed_attempts == 5
    assert cfg.rate_limit_validate == "20 per minute"
    assert cfg.rate_limit_submit == "5 per minute"
    assert cfg.max_upload_mb == 2
    assert cfg.cors_allowed_origins == ()
    assert cfg.ldap_allow_insecure is False


def test_from_env_all_values():
    cfg = Config.from_env(
        ENV
        | {
            "CODE_EXPIRY_MINUTES": "30",
            "MAX_FAILED_ATTEMPTS": "3",
            "RATE_LIMIT_VALIDATE": "10 per hour",
            "RATE_LIMIT_SUBMIT": "100 per second",
            "MAX_UPLOAD_MB": "5",
            "CORS_ALLOWED_ORIGINS": "https://a.example, https://b.example",
            "LDAP_ALLOW_INSECURE": "TRUE",
            "PROXY_TRUSTED_COUNT": "2",
            "BASE_URL": "https://signup.example.com/",
        }
    )
    assert cfg.code_expiry_minutes == 30
    assert cfg.max_failed_attempts == 3
    assert cfg.rate_limit_validate == "10 per hour"
    assert cfg.cors_allowed_origins == ("https://a.example", "https://b.example")
    assert cfg.ldap_allow_insecure is True
    assert cfg.proxy_trusted_count == 2
    assert cfg.base_url == "https://signup.example.com"  # trailing slash stripped


def test_redirect_url_optional_and_validated():
    cfg = Config.from_env(ENV | {"REDIRECT_URL": "https://chat.example.com/rooms/main"})
    assert cfg.redirect_url == "https://chat.example.com/rooms/main"
    assert Config.from_env(ENV).redirect_url == ""
    with pytest.raises(ConfigError, match="REDIRECT_URL"):
        Config.from_env(ENV | {"REDIRECT_URL": "chat.example.com"})
    with pytest.raises(ConfigError, match="REDIRECT_URL"):
        Config.from_env(ENV | {"REDIRECT_URL": "ftp://x"})


def test_base_url_subpath_is_kept():
    cfg = Config.from_env(ENV | {"BASE_URL": "https://home.appolon.dev/signup/"})
    assert cfg.base_url == "https://home.appolon.dev/signup"


def test_base_url_subpath_builds_prefixed_links():
    cfg = Config.from_env(ENV | {"BASE_URL": "https://home.appolon.dev/signup"})
    # internal API composes {BASE_URL}/register?code=...
    assert cfg.base_url + "/register?code=x" == (
        "https://home.appolon.dev/signup/register?code=x"
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"BASE_URL": "https://x.example/signup?foo=1"},
        {"BASE_URL": "https://x.example/signup#frag"},
        {"BASE_URL": "https://x.example/sign up"},
    ],
)
def test_base_url_rejects_query_fragment_and_spaces(overrides):
    with pytest.raises(ConfigError, match="BASE_URL"):
        Config.from_env(ENV | overrides)


def test_ldap_ca_cert_requires_existing_file(tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----")
    cfg = Config.from_env(ENV | {"LDAP_CA_CERT": str(ca)})
    assert cfg.ldap_ca_cert == str(ca)
    with pytest.raises(ConfigError, match="LDAP_CA_CERT"):
        Config.from_env(ENV | {"LDAP_CA_CERT": str(tmp_path / "missing.pem")})


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"BASE_URL": ""}, "BASE_URL"),
        ({"BASE_URL": "signup.example.com"}, "BASE_URL"),
        ({"BASE_URL": "ftp://x"}, "BASE_URL"),
        ({"LDAP_URL": "http://lldap:6360"}, "LDAP_URL"),
        ({"LDAP_URL": "ldaps://"}, "LDAP_URL"),
        ({"LDAP_ADMIN_DN": ""}, "LDAP_ADMIN_DN"),
        ({"DATABASE_PATH": " "}, "DATABASE_PATH"),
        ({"INTERNAL_API_KEY": "short"}, "INTERNAL_API_KEY"),
        ({"FLASK_SECRET_KEY": ""}, "FLASK_SECRET_KEY"),
        ({"CODE_EXPIRY_MINUTES": "zero"}, "CODE_EXPIRY_MINUTES"),
        ({"CODE_EXPIRY_MINUTES": "1000000"}, "CODE_EXPIRY_MINUTES"),
        ({"RATE_LIMIT_VALIDATE": "lots"}, "RATE_LIMIT_VALIDATE"),
        ({"RATE_LIMIT_SUBMIT": "20"}, "RATE_LIMIT_SUBMIT"),
        ({"MAX_UPLOAD_MB": "0"}, "MAX_UPLOAD_MB"),
        ({"PROXY_TRUSTED_COUNT": "-1"}, "PROXY_TRUSTED_COUNT"),
    ],
)
def test_from_env_rejects_bad_values(overrides, fragment):
    with pytest.raises(ConfigError, match=fragment):
        Config.from_env(ENV | overrides)


def test_from_env_rejects_wildcard_cors():
    with pytest.raises(ConfigError, match=r"\*"):
        Config.from_env(ENV | {"CORS_ALLOWED_ORIGINS": "*"})


def test_from_env_rejects_malformed_cors_origin():
    with pytest.raises(ConfigError, match="invalid origin"):
        Config.from_env(ENV | {"CORS_ALLOWED_ORIGINS": "https://a.example/path"})
