"""Telegram registration notifications."""

from __future__ import annotations

from typing import ClassVar

import pytest

from app.config import Config, ConfigError
from app.notifier import notify_account_created
from tests.conftest import SECRET, make_config


def notify_config(tmp_path, **overrides):
    overrides.setdefault("platform_name", "Acme")
    overrides.setdefault("telegram_bot_token", "123:ABC")
    overrides.setdefault("telegram_admin_ids", frozenset({111, 222}))
    return make_config(tmp_path, **overrides)


class TestNotifyAccountCreated:
    def test_notifies_every_admin_with_platform_and_display_name(self, tmp_path):
        sent = []
        notify_account_created(
            notify_config(tmp_path),
            "Jean Dupont",
            send=lambda token, chat, text: sent.append((token, chat, text)),
        )
        assert sorted(chat for _, chat, _ in sent) == [111, 222]
        token, _chat, text = sent[0]
        assert token == "123:ABC"
        assert text == "✅ Acme account created: Jean Dupont"

    def test_without_platform_uses_generic_prefix(self, tmp_path):
        sent = []
        notify_account_created(
            notify_config(tmp_path, platform_name=""),
            "Alice Smith",
            send=lambda token, chat, text: sent.append((token, chat, text)),
        )
        assert sent[0][2] == "✅ Account created: Alice Smith"

    def test_disabled_without_token(self, tmp_path):
        sent = []
        notify_account_created(
            notify_config(tmp_path, telegram_bot_token=""),
            "X",
            send=lambda token, chat, text: sent.append((token, chat, text)),
        )
        assert sent == []

    def test_disabled_without_admin_ids(self, tmp_path):
        sent = []
        notify_account_created(
            notify_config(tmp_path, telegram_admin_ids=frozenset()),
            "X",
            send=lambda token, chat, text: sent.append((token, chat, text)),
        )
        assert sent == []

    def test_production_sender_swallows_errors(self, monkeypatch):
        from app import notifier

        def boom(request, timeout=None):
            raise OSError("network down")

        monkeypatch.setattr(notifier.urllib.request, "urlopen", boom)
        notifier._send("123:ABC", 1, "text")  # must not raise


class TestConfigPlatformAndNotify:
    BASE: ClassVar[dict] = {
        "BASE_URL": "https://s.example.com",
        "LDAP_URL": "ldaps://l:636",
        "LDAP_ADMIN_DN": "uid=admin,dc=x",
        "LDAP_ADMIN_PASSWORD": "pw",
        "LDAP_BASE_DN": "dc=x",
        "DATABASE_PATH": "/var/lib/app/x.db",
        "INTERNAL_API_KEY": SECRET,
        "FLASK_SECRET_KEY": SECRET,
    }

    def test_env_parsing(self):
        cfg = Config.from_env(
            self.BASE
            | {
                "PLATFORM_NAME": "Famille",
                "TELEGRAM_BOT_TOKEN": "1:A",
                "TELEGRAM_ADMIN_IDS": "111, 222",
            }
        )
        assert cfg.platform_name == "Famille"
        assert cfg.telegram_admin_ids == frozenset({111, 222})
        assert cfg.telegram_bot_token == "1:A"

    def test_defaults_are_empty(self):
        cfg = Config.from_env(self.BASE)
        assert cfg.platform_name == ""
        assert cfg.telegram_bot_token == ""
        assert cfg.telegram_admin_ids == frozenset()

    @pytest.mark.parametrize(
        ("overrides", "fragment"),
        [
            ({"PLATFORM_NAME": "x" * 65}, "PLATFORM_NAME"),
            ({"PLATFORM_NAME": "bad\nname"}, "PLATFORM_NAME"),
            ({"TELEGRAM_ADMIN_IDS": "abc"}, "TELEGRAM_ADMIN_IDS"),
        ],
    )
    def test_rejects_bad_values(self, overrides, fragment):
        with pytest.raises(ConfigError, match=fragment):
            Config.from_env(self.BASE | overrides)
