"""Unit tests for Telegram topic_closed handling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.adapters.telegram.input_handlers import InputHandlersMixin
from teleclaude.core.models import Session, SessionAdapterMetadata, TelegramAdapterMetadata


class DummyHandlers(InputHandlersMixin):
    """Minimal mixin host for testing."""

    def __init__(self) -> None:
        self.client = Mock()
        self.user_whitelist = set()
        self._topic_message_cache = {}
        self._mcp_message_queues = {}
        self._processed_voice_messages = set()
        self._topic_ready_events = {}
        self._topic_ready_cache = set()

    def _metadata(self, **kwargs: object):  # type: ignore[override]
        return None

    async def _get_session_from_topic(self, update):  # type: ignore[override]
        return None

    def _topic_owned_by_this_bot(self, update, topic_id: int) -> bool:  # type: ignore[override]
        return True

    async def _delete_orphan_topic(self, topic_id: int) -> None:  # type: ignore[override]
        return None


@pytest.mark.asyncio
async def test_topic_closed_ignores_new_session() -> None:
    """Topic_closed should be ignored for very new sessions (race guard)."""
    handlers = DummyHandlers()

    session = Session(
        session_id="sess-123",
        computer_name="test",
        tmux_session_name="tc_sess_123",
        origin_adapter="telegram",
        title="Test",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=456)),
        created_at=datetime.now(timezone.utc),
    )

    update = SimpleNamespace(message=SimpleNamespace(message_thread_id=456))

    with (
        patch(
            "teleclaude.adapters.telegram.input_handlers.db.get_sessions_by_adapter_metadata",
            new=AsyncMock(return_value=[session]),
        ),
        patch("teleclaude.core.event_bus.event_bus.emit", new=AsyncMock()) as mock_emit,
    ):
        await handlers._handle_topic_closed(update, None)

    mock_emit.assert_not_called()


@pytest.mark.asyncio
async def test_topic_closed_handles_naive_created_at() -> None:
    """Topic_closed should handle naive created_at timestamps."""
    handlers = DummyHandlers()

    utc_naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=30)
    session = Session(
        session_id="sess-456",
        computer_name="test",
        tmux_session_name="tc_sess_456",
        origin_adapter="telegram",
        title="Test",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=789)),
        created_at=utc_naive,
    )

    update = SimpleNamespace(message=SimpleNamespace(message_thread_id=789))

    with (
        patch(
            "teleclaude.adapters.telegram.input_handlers.db.get_sessions_by_adapter_metadata",
            new=AsyncMock(return_value=[session]),
        ),
        patch("teleclaude.core.event_bus.event_bus.emit", new=AsyncMock()) as mock_emit,
    ):
        await handlers._handle_topic_closed(update, None)

    mock_emit.assert_called_once()
