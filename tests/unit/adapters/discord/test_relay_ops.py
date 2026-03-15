from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import TypedDict
from unittest.mock import AsyncMock

import pytest

from teleclaude.adapters.discord.relay_ops import RelayOperationsMixin

pytestmark = pytest.mark.unit


class DummyRelayOperations(RelayOperationsMixin):
    def __init__(self) -> None:
        self._client = SimpleNamespace(user=SimpleNamespace(id=900))
        self._get_channel = AsyncMock()


class AsyncHistory:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def __aiter__(self) -> AsyncHistory:
        self._iterator = iter(self._items)
        return self

    async def __anext__(self) -> object:
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class HistoryKwargs(TypedDict):
    after: datetime
    limit: int


class ThreadHistory:
    def __init__(self, items: list[object]) -> None:
        self._items = items
        self.history_kwargs: HistoryKwargs | None = None

    def history(self, *, after: datetime, limit: int) -> AsyncHistory:
        self.history_kwargs = {"after": after, "limit": limit}
        return AsyncHistory(self._items)


def test_is_agent_tag_matches_keyword_or_bot_mention() -> None:
    adapter = DummyRelayOperations()

    assert adapter._is_agent_tag("handoff to @agent") is True
    assert adapter._is_agent_tag("hi <@900>") is True
    assert adapter._is_agent_tag("hello there") is False


def test_sanitize_relay_text_removes_ansi_and_control_characters() -> None:
    adapter = DummyRelayOperations()

    sanitized = adapter._sanitize_relay_text("\x1b[31mred\x1b[0m\x07\nnext\tcol")

    assert sanitized == "red\nnext\tcol"


@pytest.mark.asyncio
async def test_collect_relay_messages_classifies_patterned_bot_posts_and_admin_replies() -> None:
    adapter = DummyRelayOperations()
    history = ThreadHistory(
        [
            SimpleNamespace(
                author=SimpleNamespace(bot=True, display_name="RelayBot"), content="**Alice** (discord): hello"
            ),
            SimpleNamespace(author=SimpleNamespace(bot=True, display_name="RelayBot"), content="system note"),
            SimpleNamespace(author=SimpleNamespace(bot=False, display_name="Operator"), content="reply\x1b[31m!"),
        ]
    )
    adapter._get_channel = AsyncMock(return_value=history)

    messages = await adapter._collect_relay_messages("123", datetime(2024, 1, 1))

    assert messages == [
        {"role": "Customer", "name": "Alice", "content": "hello"},
        {"role": "Admin", "name": "Operator", "content": "reply\x1b[31m!"},
    ]
    assert history.history_kwargs == {"after": datetime(2024, 1, 1), "limit": 200}
