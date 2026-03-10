"""Unit tests for daemon close-requested failure recovery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.events import SessionStatusContext, TeleClaudeEvents
from teleclaude.daemon import TeleClaudeDaemon


@pytest.mark.asyncio
async def test_close_requested_failure_restores_session_and_emits_error_status() -> None:
    """A failed close request should restore the session and emit a close_failed status."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()

    session = SimpleNamespace(session_id="sess-123", lifecycle_status="closing", closed_at=None)

    with (
        patch("teleclaude.daemon.db.get_session", new=AsyncMock(return_value=session)),
        patch("teleclaude.daemon.db.update_session", new=AsyncMock()) as mock_update_session,
        patch("teleclaude.daemon.session_cleanup.terminate_session", new=AsyncMock(side_effect=RuntimeError("boom"))),
        patch("teleclaude.daemon.event_bus.emit") as mock_emit,
    ):
        await daemon._handle_session_close_requested(
            "session_close_requested",
            SimpleNamespace(session_id="sess-123"),
        )

    mock_update_session.assert_awaited_once_with("sess-123", lifecycle_status="active")
    emitted_event, emitted_context = mock_emit.call_args.args
    assert emitted_event == TeleClaudeEvents.SESSION_STATUS
    assert isinstance(emitted_context, SessionStatusContext)
    assert emitted_context.session_id == "sess-123"
    assert emitted_context.status == "error"
    assert emitted_context.reason == "close_failed"
