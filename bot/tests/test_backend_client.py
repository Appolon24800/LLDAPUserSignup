"""BackendClient against a scripted httpx mock transport."""

from __future__ import annotations

import httpx
import pytest

from bot.backend_client import BackendClient, BackendError
from tests.conftest import run

API_KEY = "k" * 40


def make_client(handler) -> BackendClient:
    transport = httpx.MockTransport(handler)
    return BackendClient("http://backend:8000", API_KEY, transport=transport)


def ok_json(payload, status=200):
    return httpx.Response(status, json=payload)


class TestCreateCode:
    def test_success(self):
        import json

        seen = {}

        def handler(request):
            seen["path"] = request.url.path
            seen["auth"] = request.headers.get("X-Internal-API-Key")
            seen["body"] = json.loads(request.read().decode())
            return ok_json(
                {"code": "TOK", "url": "https://x/register?code=TOK",
                 "groups": ["a"], "expires_at": "2030-01-01T00:00:00+00:00"},
                status=201,
            )

        client = make_client(handler)
        result = run(client.create_code(["a"], created_by="42"))
        assert result["code"] == "TOK"
        assert seen["path"] == "/internal/codes"
        assert seen["auth"] == API_KEY
        assert seen["body"] == {"groups": ["a"], "created_by": "42"}

    def test_backend_error_detail(self):
        def handler(request):
            return ok_json(
                {"error": {"code": "validation_error", "message": "unknown groups: x"}},
                status=400,
            )

        client = make_client(handler)
        with pytest.raises(BackendError, match="unknown groups"):
            run(client.create_code(["x"], created_by="1"))

    def test_unauthorized(self):
        client = make_client(lambda request: ok_json({"error": {}}, status=401))
        with pytest.raises(BackendError, match="internal API key"):
            run(client.list_groups())


class TestListAndRevoke:
    def test_list_codes(self):
        def handler(request):
            assert request.url.path == "/internal/codes"
            return ok_json({"codes": [{"code_hint": "Ab…"}]})

        assert run(make_client(handler).list_codes()) == [{"code_hint": "Ab…"}]

    def test_revoke_true_false(self):
        client = make_client(lambda request: ok_json({"revoked": True}))
        assert run(client.revoke_code("TOK")) is True
        client = make_client(lambda request: ok_json({"revoked": False}))
        assert run(client.revoke_code("TOK")) is False

    def test_list_groups(self):
        client = make_client(lambda request: ok_json({"groups": ["a", "b"]}))
        assert run(client.list_groups()) == ["a", "b"]


class TestNetworkFailures:
    def test_unreachable(self):
        def handler(request):
            raise httpx.ConnectError("nope")

        with pytest.raises(BackendError, match="unreachable"):
            run(make_client(handler).list_groups())

    def test_malformed_error_body(self):
        client = make_client(lambda request: httpx.Response(500, text="<html>"))
        with pytest.raises(BackendError, match="500"):
            run(client.list_groups())
