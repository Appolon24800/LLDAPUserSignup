"""Config parsing, admin allow-list, throttling, command parsing."""

from __future__ import annotations

import pytest

from bot.auth import NOT_AUTHORIZED_MESSAGE, UserRateLimiter, is_admin
from bot.config import BotConfig, BotConfigError
from bot.parsing import parse_group_args, parse_revoke_arg, split_command

SECRET = "k" * 40

ENV = {
    "TELEGRAM_BOT_TOKEN": "123:ABC",
    "TELEGRAM_ADMIN_IDS": "111, 222",
    "BACKEND_URL": "http://backend:8000",
    "INTERNAL_API_KEY": SECRET,
}


class TestBotConfig:
    def test_minimal(self):
        cfg = BotConfig.from_env(ENV)
        assert cfg.admin_ids == frozenset({111, 222})
        assert cfg.backend_url == "http://backend:8000"

    @pytest.mark.parametrize(
        ("overrides", "fragment"),
        [
            ({"TELEGRAM_BOT_TOKEN": ""}, "TELEGRAM_BOT_TOKEN"),
            ({"TELEGRAM_ADMIN_IDS": ""}, "TELEGRAM_ADMIN_IDS"),
            ({"TELEGRAM_ADMIN_IDS": "abc"}, "TELEGRAM_ADMIN_IDS"),
            ({"TELEGRAM_ADMIN_IDS": ","}, "TELEGRAM_ADMIN_IDS"),
            ({"BACKEND_URL": "backend:8000"}, "BACKEND_URL"),
            ({"BACKEND_URL": "ftp://x"}, "BACKEND_URL"),
            ({"INTERNAL_API_KEY": "short"}, "INTERNAL_API_KEY"),
        ],
    )
    def test_rejects_bad_values(self, overrides, fragment):
        with pytest.raises(BotConfigError, match=fragment):
            BotConfig.from_env(ENV | overrides)

    def test_trailing_slash_stripped(self):
        cfg = BotConfig.from_env(ENV | {"BACKEND_URL": "http://backend:8000/"})
        assert cfg.backend_url == "http://backend:8000"


class TestIsAdmin:
    def test_member(self):
        assert is_admin(111, frozenset({111, 222})) is True

    def test_non_member(self):
        assert is_admin(333, frozenset({111, 222})) is False

    def test_none(self):
        assert is_admin(None, frozenset({111})) is False


class TestUserRateLimiter:
    def test_allows_up_to_limit(self):
        now = [0.0]
        rl = UserRateLimiter(max_calls=3, window_seconds=60, clock=lambda: now[0])
        assert all(rl.allow(1) for _ in range(3))
        assert rl.allow(1) is False

    def test_window_slides(self):
        now = [0.0]
        rl = UserRateLimiter(max_calls=2, window_seconds=60, clock=lambda: now[0])
        rl.allow(1)
        rl.allow(1)
        assert rl.allow(1) is False
        now[0] = 61.0
        assert rl.allow(1) is True

    def test_per_user(self):
        rl = UserRateLimiter(max_calls=1, window_seconds=60, clock=lambda: 0.0)
        assert rl.allow(1) is True
        assert rl.allow(2) is True

    def test_message_is_generic(self):
        assert "not authorized" in NOT_AUTHORIZED_MESSAGE.lower()


class TestParseGroupArgs:
    def test_comma_separated(self):
        assert parse_group_args("family, media ,admin") == ["family", "media", "admin"]

    def test_space_separated(self):
        assert parse_group_args("family media") == ["family", "media"]

    def test_mixed(self):
        assert parse_group_args("family, media admin") == ["family", "media", "admin"]

    def test_deduplicates(self):
        assert parse_group_args("a a, a") == ["a"]

    def test_empty(self):
        assert parse_group_args("") == []
        assert parse_group_args(None) == []
        assert parse_group_args("   , , ") == []

    def test_strips_formatting(self):
        assert parse_group_args("*family* `media`") == ["family", "media"]

    def test_caps_at_max(self):
        args = " ".join(f"g{i}" for i in range(40))
        assert len(parse_group_args(args)) == 20


class TestParseRevokeArg:
    def test_single(self):
        assert parse_revoke_arg("AbCd1234xyz") == "AbCd1234xyz"

    def test_takes_first(self):
        assert parse_revoke_arg("code1 code2") == "code1"

    def test_none(self):
        assert parse_revoke_arg("") is None
        assert parse_revoke_arg(None) is None


class TestSplitCommand:
    def test_plain(self):
        assert split_command("/gen family") == ("/gen", "family")

    def test_bot_name(self):
        assert split_command("/gen@MyBot family,media") == ("/gen", "family,media")

    def test_no_args(self):
        assert split_command("/list") == ("/list", "")

    def test_not_command(self):
        assert split_command("hello") == ("", "")
        assert split_command(None) == ("", "")
