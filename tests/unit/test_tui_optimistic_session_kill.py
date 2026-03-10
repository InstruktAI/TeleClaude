"""Unit tests for optimistic session kill behavior in TelecApp."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.cli.models import SessionLifecycleStatusEvent
from teleclaude.cli.tui.app import TelecApp
from teleclaude.cli.tui.messages import KillSessionRequest, SessionClosed


@pytest.mark.asyncio
async def test_on_kill_session_request_hides_session_after_success() -> None:
    """A successful close intent should hide the session immediately in the TUI."""
    sessions_view = MagicMock()
    app = SimpleNamespace(
        api=SimpleNamespace(end_session=AsyncMock(return_value=True)),
        query_one=MagicMock(return_value=sessions_view),
        notify=MagicMock(),
    )

    await TelecApp.on_kill_session_request.__wrapped__(app, KillSessionRequest("sess-1", "local"))

    app.api.end_session.assert_awaited_once_with("sess-1", "local")
    sessions_view.optimistically_hide_session.assert_called_once_with("sess-1")


def test_handle_ws_event_close_failed_refreshes_and_notifies() -> None:
    """close_failed should tell the user and trigger an authoritative refresh."""
    app = SimpleNamespace(
        notify=MagicMock(),
        _refresh_data=MagicMock(),
    )
    event = SessionLifecycleStatusEvent(
        event="session_status",
        session_id="sess-1",
        status="error",
        reason="close_failed",
        timestamp="2026-03-10T00:00:00Z",
    )

    TelecApp._handle_ws_event(app, event)

    app.notify.assert_called_once_with("Session sess-1 failed to close", severity="error")
    app._refresh_data.assert_called_once_with()


def test_on_session_closed_confirms_hidden_session_before_refresh() -> None:
    """A confirmed close should finalize local optimistic hide before refreshing."""
    sessions_view = MagicMock()
    app = SimpleNamespace(
        _session_agents={"sess-1": "codex"},
        query_one=MagicMock(return_value=sessions_view),
        _refresh_data=MagicMock(),
    )

    TelecApp.on_session_closed(app, SessionClosed("sess-1"))

    assert "sess-1" not in app._session_agents
    sessions_view.confirm_session_closed.assert_called_once_with("sess-1")
    app._refresh_data.assert_called_once_with()
