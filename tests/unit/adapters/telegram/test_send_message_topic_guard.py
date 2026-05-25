"""Tests for send_message behavior in private-chat mode."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.adapters.telegram.message_ops import EditContext, MessageOperationsMixin
from teleclaude.core.models import MessageMetadata, Session

pytestmark = pytest.mark.unit


class _StubMessageOps(MessageOperationsMixin):
    """Minimal concrete implementation for testing MessageOperationsMixin."""

    def __init__(self) -> None:
        self._pending_edits: dict[str, EditContext] = {}
        self._last_edit_hash: dict[str, str] = {}
        self._bot = MagicMock()
        self._bot.send_message = AsyncMock(return_value=MagicMock(message_id=101))

    @property
    def bot(self) -> MagicMock:
        return self._bot

    def _ensure_started(self) -> None:
        pass


def _make_session(session_id: str = "sess-1", user_id: str | None = None) -> Session:
    return Session(
        session_id=session_id,
        computer_name="x",
        tmux_session_name=f"t-{session_id}",
        title="S",
        origin_metadata={"user_id": user_id} if user_id is not None else {},
    )


@pytest.mark.asyncio
async def test_send_message_returns_empty_string_when_user_id_missing() -> None:
    ops = _StubMessageOps()
    session = _make_session(user_id=None)
    result = await ops.send_message(session, "Hello", metadata=MessageMetadata())
    assert result == ""
    ops.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_send_message_proceeds_when_user_id_present() -> None:
    ops = _StubMessageOps()
    session = _make_session(user_id="123456789")
    result = await ops.send_message(session, "Hello", metadata=MessageMetadata())
    assert result != ""
    ops.bot.send_message.assert_called_once()
