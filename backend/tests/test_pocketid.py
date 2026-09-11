"""PocketID LDAP sync trigger."""

from __future__ import annotations

from app.pocketid import trigger_ldap_sync
from tests.conftest import make_config


def pocketid_config(tmp_path, **overrides):
    overrides.setdefault("pocketid_url", "https://id.example.com")
    overrides.setdefault("pocketid_api_key", "pid-test-key")
    return make_config(tmp_path, **overrides)


class TestTriggerLdapSync:
    def test_sends_once_with_url_and_key(self, tmp_path):
        sent = []
        trigger_ldap_sync(
            pocketid_config(tmp_path),
            send=lambda url, key: sent.append((url, key)),
        )
        assert sent == [("https://id.example.com", "pid-test-key")]

    def test_disabled_without_url(self, tmp_path):
        sent = []
        trigger_ldap_sync(
            pocketid_config(tmp_path, pocketid_url=""),
            send=lambda url, key: sent.append((url, key)),
        )
        assert sent == []

    def test_disabled_without_api_key(self, tmp_path):
        sent = []
        trigger_ldap_sync(
            pocketid_config(tmp_path, pocketid_api_key=""),
            send=lambda url, key: sent.append((url, key)),
        )
        assert sent == []

    def test_production_sender_swallows_errors(self, monkeypatch):
        from app import pocketid

        def boom(request, timeout=None):
            raise OSError("network down")

        monkeypatch.setattr(pocketid.urllib.request, "urlopen", boom)
        pocketid._send("https://id.example.com", "pid-test-key")  # must not raise

    def test_production_sender_posts_sync_endpoint(self, monkeypatch):
        from app import pocketid

        calls = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b""

        def fake_urlopen(request, timeout=None):
            # urllib capitalizes header names: "X-API-Key" -> "X-api-key".
            calls.append(
                (request.full_url, request.get_method(), request.headers.get("X-api-key"))
            )
            return FakeResponse()

        monkeypatch.setattr(pocketid.urllib.request, "urlopen", fake_urlopen)
        pocketid._send("https://id.example.com", "pid-test-key")
        assert calls == [
            (
                "https://id.example.com/api/application-configuration/sync-ldap",
                "POST",
                "pid-test-key",
            )
        ]
