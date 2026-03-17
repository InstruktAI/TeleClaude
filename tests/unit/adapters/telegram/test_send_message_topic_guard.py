"""Tests for send_message behavior when topic_id is None."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.adapters.telegram.message_ops import EditContext, MessageOperationsMixin
from teleclaude.core.models import MessageMetadata, Session, SessionAdapterMetadata, TelegramAdapterMetadata

pytestmark = pytest.mark.unit


class _StubMessageOps(MessageOperationsMixin):
    """Minimal concrete implementation for testing MessageOperationsMixin."""

    def __init__(self) -> None:
        self._pending_edits: dict[str, EditContext] = {}
        self._last_edit_hash: dict[str, str] = {}
        self.supergroup_id = 12345
        self._bot = MagicMock()
        self._bot.send_message = AsyncMock(return_value=MagicMock(message_id=101))
        self._bot.edit_message_text = AsyncMock()
        self.waited_for_topic: list[tuple[int, str]] = []

    @property
    def bot(self) -> MagicMock:
        return self._bot

    def _ensure_started(self) -> None:
        pass

    async def _wait_for_topic_ready(self, topic_id: int, title: str) -> None:
        self.waited_for_topic.append((topic_id, title))


def _make_session(session_id: str = "sess-1", topic_id: int | None = None) -> Session:
    return Session(
        session_id=session_id,
        computer_name="test-computer",
        tmux_session_name=f"tmux-{session_id}",
        title="Test Session",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=topic_id)),
    )


@pytest.mark.asyncio
async def test_send_message_returns_empty_string_when_topic_id_missing() -> None:
    ops = _StubMessageOps()
    session = _make_session(topic_id=None)
    result = await ops.send_message(session, "Hello", metadata=MessageMetadata())
    assert result == ""
    ops.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_send_message_proceeds_when_topic_id_present() -> None:
    ops = _StubMessageOps()
    session = _make_session(topic_id=123)
    result = await ops.send_message(session, "Hello", metadata=MessageMetadata())
    # Should have called the bot API (returns message_id as string)
    assert result != ""
    ops.bot.send_message.assert_called_once()
