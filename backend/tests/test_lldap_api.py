"""LLDAP GraphQL client for group membership."""

from __future__ import annotations

import base64
import json
import time

import pytest

from app.ldap_service import LdapServiceError
from app.lldap_api import LldapGraphQL, admin_user_from_dn, derive_http_url


def fake_jwt(expires_in: int = 3600) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": int(time.time()) + expires_in}).encode()
    ).decode().rstrip("=")
    return f"h.{payload}.s"


class Router:
    """Callable standing in for LldapGraphQL._post, routing by URL suffix."""

    def __init__(self):
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url, payload, headers):
        self.calls.append((url, payload, headers))
        if url.endswith("/auth/simple/login"):
            if payload != {"username": "admin", "password": "pw"}:
                raise OSError("bad credentials")
            return {"token": fake_jwt()}
        if url.endswith("/api/graphql"):
            if not headers.get("Authorization", "").startswith("Bearer "):
                raise OSError("missing bearer token")
            query = payload["query"]
            if "GroupId" in query:
                name = payload["variables"]["name"]
                if name == "missing":
                    return {"data": {"groups": []}}
                return {"data": {"groups": [{"id": 42}]}}
            if "AddMember" in query:
                if payload["variables"] == {"user": "dave", "group": 42}:
                    return {"data": {"addUserToGroup": {"success": True}}}
                return {"data": {"addUserToGroup": {"success": False}}}
        raise OSError(f"unexpected url {url}")


def make_client(router=None):
    return LldapGraphQL("http://lldap:17170", "admin", "pw", post=router or Router())


class TestHappyPath:
    def test_login_lookup_add(self):
        router = Router()
        api = make_client(router)
        api.add_user_to_group("dave", "family")

        assert [url.rsplit("/", 1)[-1] for url, _, _ in router.calls] == [
            "login", "graphql", "graphql"
        ]
        group_query = router.calls[1][1]
        assert group_query["variables"] == {"name": "family"}
        add_mutation = router.calls[2][1]
        assert add_mutation["variables"] == {"user": "dave", "group": 42}

    def test_token_is_cached_across_calls(self):
        router = Router()
        api = make_client(router)
        api.add_user_to_group("dave", "family")
        api.add_user_to_group("dave", "media")
        logins = [c for c in router.calls if c[0].endswith("/login")]
        assert len(logins) == 1


class TestErrors:
    def test_unknown_group(self):
        api = make_client()
        with pytest.raises(LdapServiceError, match="not found"):
            api.add_user_to_group("dave", "missing")

    def test_graphql_errors_surface(self):
        def post(url, payload, headers):
            if url.endswith("/login"):
                return {"token": fake_jwt()}
            return {"errors": [{"message": "bad schema"}]}

        api = LldapGraphQL("http://lldap:17170", "admin", "pw", post=post)
        with pytest.raises(LdapServiceError, match="bad schema"):
            api.add_user_to_group("dave", "family")

    def test_failed_mutation(self):
        api = make_client()
        with pytest.raises(LdapServiceError, match="failed"):
            api.add_user_to_group("mallory", "family")  # router: success False

    def test_unreachable(self):
        def post(url, payload, headers):
            raise OSError("connection refused")

        api = LldapGraphQL("http://lldap:17170", "admin", "pw", post=post)
        with pytest.raises(LdapServiceError, match="unreachable"):
            api.add_user_to_group("dave", "family")

    def test_login_without_token(self):
        api = LldapGraphQL(
            "http://lldap:17170", "admin", "pw", post=lambda *a: {"detail": "nope"}
        )
        with pytest.raises(LdapServiceError, match="no token"):
            api.add_user_to_group("dave", "family")


class TestHelpers:
    def test_derive_http_url(self):
        assert derive_http_url("ldap://192.168.1.39:3890") == "http://192.168.1.39:17170"
        assert derive_http_url("ldaps://lldap.example:6360") == "https://lldap.example:17170"

    def test_admin_user_from_dn(self):
        assert admin_user_from_dn("uid=admin,ou=people,dc=x") == "admin"
        assert admin_user_from_dn("cn=weird,dc=x") == "cn=weird,dc=x"
        assert admin_user_from_dn("uid=solo") == "solo"
