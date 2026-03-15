from __future__ import annotations

from unittest.mock import Mock

import pytest

from teleclaude.api_models import SessionDTO
from teleclaude.cli.models import SessionStartedEvent
from teleclaude.cli.tui import app_ws
from teleclaude.cli.tui.messages import AgentActivity, SessionClosed


class _SessionsView:
    def __init__(self) -> None:
        self.activity_calls: list[tuple[str, str, str | None]] = []
        self.closed: list[str] = []

    def update_activity(self, session_id: str, activity_type: str, detail: str | None = None) -> None:
        self.activity_calls.append((session_id, activity_type, detail))

    def confirm_session_closed(self, session_id: str) -> None:
        self.closed.append(session_id)


class _WsApp(app_ws.TelecAppWsMixin):
    def __init__(self, sessions_view: _SessionsView) -> None:
        self._sessions_view = sessions_view
        self._post_messages: list[object] = []
        self._session_agents = {"session-1": "codex"}
        self._activity_trigger = None
        self.notify = Mock()
        self._refresh_data = Mock()

    def query_one(self, selector: str, *_args: object) -> object:
        if selector == "#sessions-view":
            return self._sessions_view
        raise AssertionError(selector)

    def post_message(self, message: object) -> None:
        self._post_messages.append(message)


@pytest.mark.unit
def test_handle_ws_event_posts_session_started_messages() -> None:
    sessions_view = _SessionsView()
    app = _WsApp(sessions_view)
    session = SessionDTO(session_id="session-1", title="title", status="idle", computer="c1")

    app._handle_ws_event(SessionStartedEvent(event="session_started", data=session))

    assert len(app._post_messages) == 1
    assert type(app._post_messages[0]).__name__ == "SessionStarted"
    assert app._post_messages[0].session.session_id == "session-1"


@pytest.mark.unit
def test_on_agent_activity_strips_duplicate_tool_name_prefix_from_preview() -> None:
    sessions_view = _SessionsView()
    app = _WsApp(sessions_view)
    message = AgentActivity(
        session_id="session-1",
        activity_type="tool_use",
        canonical_type="tool_use",
        tool_name="shell",
        tool_preview="shell ls -la",
    )

    app.on_agent_activity(message)

    assert len(sessions_view.activity_calls) == 1
    sid, atype, detail = sessions_view.activity_calls[0]
    assert sid == "session-1"
    assert atype == "tool_use"
    assert detail is not None and "ls -la" in detail


@pytest.mark.unit
def test_on_session_closed_drops_cached_agent_and_refreshes_data() -> None:
    sessions_view = _SessionsView()
    app = _WsApp(sessions_view)

    app.on_session_closed(SessionClosed("session-1"))

    assert app._session_agents == {}
    assert sessions_view.closed == ["session-1"]
    app._refresh_data.assert_called_once_with()
