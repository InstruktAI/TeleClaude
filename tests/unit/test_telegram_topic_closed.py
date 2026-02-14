"""Unit tests for Telegram topic_closed handling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.adapters.telegram.input_handlers import InputHandlersMixin
from teleclaude.core.models import Session, SessionAdapterMetadata, TelegramAdapterMetadata
from teleclaude.core.origins import InputOrigin


class DummyHandlers(InputHandlersMixin):
    """Minimal mixin host for testing."""

    def __init__(self) -> None:
        self.client = Mock()
        self.user_whitelist = set()
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
        last_input_origin=InputOrigin.TELEGRAM.value,
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
        patch("teleclaude.core.event_bus.event_bus.emit", new=Mock()) as mock_emit,
    ):
        await handlers._handle_topic_closed(update, None)

    assert mock_emit.call_args is None


@pytest.mark.asyncio
async def test_topic_closed_handles_naive_created_at() -> None:
    """Topic_closed should handle naive created_at timestamps."""
    handlers = DummyHandlers()

    utc_naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=30)
    session = Session(
        session_id="sess-456",
        computer_name="test",
        tmux_session_name="tc_sess_456",
        last_input_origin=InputOrigin.TELEGRAM.value,
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
        patch("teleclaude.core.event_bus.event_bus.emit", new=Mock()) as mock_emit,
    ):
        await handlers._handle_topic_closed(update, None)

    assert mock_emit.call_args is not None


@pytest.mark.asyncio
async def test_topic_closed_re_emits_for_closed_session() -> None:
    """Topic_closed should re-emit session_closed when topic maps to an already closed session."""
    handlers = DummyHandlers()

    session = Session(
        session_id="sess-closed",
        computer_name="test",
        tmux_session_name="tc_sess_closed",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Closed",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=456)),
        created_at=datetime.now(timezone.utc) - timedelta(minutes=30),
        closed_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        lifecycle_status="closed",
    )

    update = SimpleNamespace(message=SimpleNamespace(message_thread_id=456))

    with (
        patch(
            "teleclaude.adapters.telegram.input_handlers.db.get_sessions_by_adapter_metadata",
            new=AsyncMock(return_value=[session]),
        ),
        patch("teleclaude.core.event_bus.event_bus.emit", new=Mock()) as mock_emit,
    ):
        await handlers._handle_topic_closed(update, None)

    assert mock_emit.call_count == 1


@pytest.mark.asyncio
async def test_topic_closed_re_emits_for_closing_session() -> None:
    """Topic_closed should re-emit session_closed when topic maps to a closing session."""
    handlers = DummyHandlers()

    session = Session(
        session_id="sess-closing",
        computer_name="test",
        tmux_session_name="tc_sess_closing",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Closing",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=789)),
        created_at=datetime.now(timezone.utc),
        lifecycle_status="closing",
    )

    update = SimpleNamespace(message=SimpleNamespace(message_thread_id=789))

    with (
        patch(
            "teleclaude.adapters.telegram.input_handlers.db.get_sessions_by_adapter_metadata",
            new=AsyncMock(return_value=[session]),
        ),
        patch("teleclaude.core.event_bus.event_bus.emit", new=Mock()) as mock_emit,
    ):
        await handlers._handle_topic_closed(update, None)

    assert mock_emit.call_count == 1


@pytest.mark.asyncio
async def test_text_message_with_closed_session_replays_session_closed() -> None:
    """Text handler should emit session_closed when topic maps to a closed session."""
    handlers = DummyHandlers()
    handlers.user_whitelist = {12345}

    message = SimpleNamespace(
        message_thread_id=456,
        message_id=777,
        text="hi",
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=12345),
        effective_message=message,
        message=message,
        edited_message=None,
    )

    session = Session(
        session_id="sess-closed-2",
        computer_name="test",
        tmux_session_name="tc_sess_closed_2",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Closed 2",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=456)),
        created_at=datetime.now(timezone.utc) - timedelta(minutes=30),
        closed_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        lifecycle_status="closed",
    )

    with (
        patch(
            "teleclaude.adapters.telegram.input_handlers.db.get_sessions_by_adapter_metadata",
            new=AsyncMock(return_value=[session]),
        ),
        patch("teleclaude.core.event_bus.event_bus.emit", new=Mock()) as mock_emit,
    ):
        await handlers._handle_text_message(update, None)

    assert mock_emit.call_count == 1


@pytest.mark.asyncio
async def test_text_message_with_closing_session_replays_session_closed() -> None:
    """Text handler should emit session_closed when topic maps to a closing session."""
    handlers = DummyHandlers()
    handlers.user_whitelist = {12345}

    message = SimpleNamespace(
        message_thread_id=789,
        message_id=778,
        text="hi",
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=12345),
        effective_message=message,
        message=message,
        edited_message=None,
    )

    session = Session(
        session_id="sess-closing-2",
        computer_name="test",
        tmux_session_name="tc_sess_closing_2",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Closing 2",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=789)),
        created_at=datetime.now(timezone.utc),
        lifecycle_status="closing",
    )

    with (
        patch(
            "teleclaude.adapters.telegram.input_handlers.db.get_sessions_by_adapter_metadata",
            new=AsyncMock(return_value=[session]),
        ),
        patch("teleclaude.core.event_bus.event_bus.emit", new=Mock()) as mock_emit,
    ):
        await handlers._handle_text_message(update, None)

    assert mock_emit.call_count == 1
