"""Handler behaviour with fake Telegram updates and a fake backend client."""

from __future__ import annotations

from bot import handlers
from bot.auth import UserRateLimiter
from bot.backend_client import BackendError
from tests.conftest import FakeContext, FakeUpdate, run

ADMIN = 111
NOT_ADMIN = 999


class FakeBackend:
    def __init__(self, groups=("family", "media", "admin")):
        self.groups = list(groups)
        self.created = []
        self.revoked = []

    async def list_groups(self):
        return self.groups

    async def create_code(self, groups, created_by):
        self.created.append((groups, created_by))
        return {
            "code": "TOKEN123",
            "url": "https://signup.example.com/register?code=TOKEN123",
            "groups": groups,
            "expires_at": "2030-01-01T00:00:00+00:00",
        }

    async def list_codes(self):
        return [
            {
                "code_hint": "TOK…",
                "groups": ["family"],
                "created_by": "111",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "failed_attempts": 0,
            }
        ]

    async def revoke_code(self, code):
        self.revoked.append(code)
        return True


def make_context(backend=None):
    return FakeContext(
        bot_data={
            "admin_ids": frozenset({ADMIN}),
            "rate_limiter": UserRateLimiter(max_calls=100),
            "backend": backend or FakeBackend(),
        }
    )


class TestAuthorization:
    def test_non_admin_gets_generic_reply(self):
        update = FakeUpdate(user_id=NOT_ADMIN, text="/gen")
        context = make_context()
        run(handlers.cmd_gen(update, context))
        reply = update.effective_message.last_reply
        assert reply == "⛔ Not authorized."
        assert "picker" not in context.user_data

    def test_admin_proceeds(self):
        update = FakeUpdate(user_id=ADMIN, text="/gen")
        context = make_context()
        run(handlers.cmd_gen(update, context))
        assert "picker" in context.user_data

    def test_throttled_user_told_to_slow_down(self):
        update = FakeUpdate(user_id=ADMIN, text="/gen")
        context = make_context()
        context.bot_data["rate_limiter"] = UserRateLimiter(max_calls=1)
        run(handlers.cmd_gen(update, context))  # consumes the allowance
        update2 = FakeUpdate(user_id=ADMIN, text="/gen")
        run(handlers.cmd_gen(update2, context))
        assert update2.effective_message.last_reply.startswith("⏳")


class TestGen:
    def test_no_args_opens_picker(self):
        update = FakeUpdate(user_id=ADMIN, text="/gen")
        context = make_context()
        run(handlers.cmd_gen(update, context))
        text, kwargs = update.effective_message.replies[-1]
        assert "Select the groups" in text
        assert kwargs.get("reply_markup") is not None

    def test_with_args_preselects(self):
        update = FakeUpdate(user_id=ADMIN, text="/gen family, media")
        context = make_context()
        run(handlers.cmd_gen(update, context))
        assert context.user_data["picker"].selected == {"family", "media"}

    def test_unknown_args_warns_and_ignores(self):
        update = FakeUpdate(user_id=ADMIN, text="/gen hackers")
        context = make_context()
        run(handlers.cmd_gen(update, context))
        replies = [text for text, _ in update.effective_message.replies]
        assert any("Unknown groups: hackers" in text for text in replies)
        # The picker still opens, without the invalid preselection.
        assert context.user_data["picker"].selected == set()

    def test_backend_down(self):
        class Down(FakeBackend):
            async def list_groups(self):
                raise BackendError("backend unreachable")

        update = FakeUpdate(user_id=ADMIN, text="/gen")
        context = make_context(backend=Down())
        run(handlers.cmd_gen(update, context))
        assert "Cannot reach" in update.effective_message.last_reply


class TestPickerCallback:
    def test_full_flow(self):
        backend = FakeBackend()
        context = make_context(backend)
        # open picker
        run(handlers.cmd_gen(FakeUpdate(user_id=ADMIN, text="/gen"), context))
        # select 'family' (index 0 of sorted [admin, family, media])
        run(handlers.on_picker_callback(FakeUpdate(user_id=ADMIN, callback_data="g:1"), context))
        # confirm
        update = FakeUpdate(user_id=ADMIN, callback_data="ok")
        run(handlers.on_picker_callback(update, context))
        final_text = update.callback_query.message.last_reply
        assert "TOKEN123" in final_text
        assert "https://signup.example.com/register?code=TOKEN123" in final_text
        assert "Single use" in final_text
        assert backend.created == [(["family"], "111")]
        assert "picker" not in context.user_data  # cleared

    def test_cancel(self):
        context = make_context()
        run(handlers.cmd_gen(FakeUpdate(user_id=ADMIN, text="/gen"), context))
        update = FakeUpdate(user_id=ADMIN, callback_data="cx")
        run(handlers.on_picker_callback(update, context))
        assert "Cancelled" in update.callback_query.message.last_reply
        assert "picker" not in context.user_data

    def test_confirm_without_selection(self):
        context = make_context()
        run(handlers.cmd_gen(FakeUpdate(user_id=ADMIN, text="/gen"), context))
        update = FakeUpdate(user_id=ADMIN, callback_data="ok")
        run(handlers.on_picker_callback(update, context))
        assert "at least one group" in update.callback_query.message.last_reply
        assert "picker" in context.user_data  # still active

    def test_expired_picker(self):
        context = make_context()  # no picker in user_data
        update = FakeUpdate(user_id=ADMIN, callback_data="g:1")
        run(handlers.on_picker_callback(update, context))
        assert "expired" in update.callback_query.message.last_reply

    def test_unknown_callback_ignored(self):
        context = make_context()
        run(handlers.cmd_gen(FakeUpdate(user_id=ADMIN, text="/gen"), context))
        update = FakeUpdate(user_id=ADMIN, callback_data="garbage")
        run(handlers.on_picker_callback(update, context))
        assert update.callback_query.message.replies == []  # nothing edited

    def test_non_admin_cannot_use_picker(self):
        context = make_context()
        update = FakeUpdate(user_id=NOT_ADMIN, callback_data="ok")
        run(handlers.on_picker_callback(update, context))
        # callback path: admin_only replies via effective_message
        assert update.effective_message.last_reply == "⛔ Not authorized."


class TestList:
    def test_formats_codes(self):
        update = FakeUpdate(user_id=ADMIN, text="/list")
        run(handlers.cmd_list(update, make_context()))
        reply = update.effective_message.last_reply
        assert "TOK…" in reply
        assert "family" in reply

    def test_empty(self):
        class Empty(FakeBackend):
            async def list_codes(self):
                return []

        update = FakeUpdate(user_id=ADMIN, text="/list")
        run(handlers.cmd_list(update, make_context(backend=Empty())))
        assert "No active codes" in update.effective_message.last_reply

    def test_non_admin(self):
        update = FakeUpdate(user_id=NOT_ADMIN, text="/list")
        run(handlers.cmd_list(update, make_context()))
        assert update.effective_message.last_reply == "⛔ Not authorized."


class TestRevoke:
    def test_revokes(self):
        backend = FakeBackend()
        update = FakeUpdate(user_id=ADMIN, text="/revoke TOKEN123")
        run(handlers.cmd_revoke(update, make_context(backend=backend)))
        assert "revoked" in update.effective_message.last_reply.lower()
        assert backend.revoked == ["TOKEN123"]

    def test_missing_arg(self):
        update = FakeUpdate(user_id=ADMIN, text="/revoke")
        run(handlers.cmd_revoke(update, make_context()))
        assert "Usage" in update.effective_message.last_reply

    def test_not_found(self):
        class Nope(FakeBackend):
            async def revoke_code(self, code):
                return False

        update = FakeUpdate(user_id=ADMIN, text="/revoke X")
        run(handlers.cmd_revoke(update, make_context(backend=Nope())))
        assert "not found" in update.effective_message.last_reply.lower()


class TestRelativeExpiry:
    def test_formats(self):
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        assert handlers._relative_expiry((now + timedelta(minutes=30)).isoformat()) in {
            "in 29 min",
            "in 30 min",
        }
        hours = handlers._relative_expiry((now + timedelta(hours=2, minutes=5)).isoformat())
        assert hours in {"in 2 h 4 min", "in 2 h 5 min"}
        past = handlers._relative_expiry((now - timedelta(minutes=5)).isoformat())
        assert past == "less than a minute"
        assert handlers._relative_expiry("") == ""
        assert handlers._relative_expiry("garbage") == ""
