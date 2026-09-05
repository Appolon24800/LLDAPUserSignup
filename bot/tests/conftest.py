"""Shared helpers for bot tests: a tiny async runner and fake Telegram objects."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace


def run(coro):
    return asyncio.run(coro)


class FakeMessage:
    def __init__(self):
        self.replies: list[tuple] = []
        self.text = "/start"

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))
        return SimpleNamespace(text=text)

    @property
    def last_reply(self) -> str:
        return self.replies[-1][0]


class FakeUser:
    def __init__(self, user_id, username="tester"):
        self.id = user_id
        self.username = username


class FakeUpdate:
    def __init__(self, user_id=1, text="/start", callback_data=None):
        self.effective_user = FakeUser(user_id)
        self.callback_query = None
        if callback_data is not None:
            self.callback_query = SimpleNamespace(data=callback_data, message=FakeMessage())
            self.effective_message = self.callback_query.message
        else:
            self.effective_message = FakeMessage()
            self.effective_message.text = text


class FakeContext:
    def __init__(self, bot_data=None):
        self.bot_data = bot_data or {}
        self.user_data: dict = {}
