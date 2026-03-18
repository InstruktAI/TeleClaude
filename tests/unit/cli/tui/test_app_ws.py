from __future__ import annotations

from unittest.mock import Mock

import pytest

from teleclaude.api_models import SessionDTO
from teleclaude.cli.models import SessionStartedEvent
from teleclaude.cli.tui import app_ws
from teleclaude.cli.tui.messages import AgentActivity, SessionClosed


class _PaneBridge:
    def __init__(self) -> None:
        self.updated_sessions: list[object] = []
        self.removed_sessions: list[str] = []

    def update_single_session(self, session: object) -> None:
        self.updated_sessions.append(session)

    def remove_session(self, session_id: str) -> None:
        self.removed_sessions.append(session_id)


class _SessionsView:
    def __init__(self) -> None:
        self.activity_calls: list[tuple[str, str, str | None]] = []
        self.closed: list[str] = []
        self.updated: list[object] = []
        self.pending_applied: int = 0

    def update_activity(self, session_id: str, activity_type: str, detail: str | None = None) -> None:
        self.activity_calls.append((session_id, activity_type, detail))

    def confirm_session_closed(self, session_id: str) -> None:
        self.closed.append(session_id)

    def update_session(self, session: object) -> None:
        self.updated.append(session)

    def _apply_pending_selection(self) -> None:
        self.pending_applied += 1


class _WsApp(app_ws.TelecAppWsMixin):
    def __init__(self, sessions_view: _SessionsView, pane_bridge: _PaneBridge) -> None:
        self._sessions_view = sessions_view
        self._pane_bridge = pane_bridge
        self._post_messages: list[object] = []
        self._session_agents = {"session-1": "codex"}
        self._activity_trigger = None
        self.notify = Mock()
        self._refresh_data = Mock()

    def query_one(self, selector: str, *_args: object) -> object:
        if selector == "#sessions-view":
            return self._sessions_view
        if selector == "#pane-bridge":
            return self._pane_bridge
        raise AssertionError(selector)

    def post_message(self, message: object) -> None:
        self._post_messages.append(message)


@pytest.mark.unit
def test_handle_ws_event_posts_session_started_messages() -> None:
    sessions_view = _SessionsView()
    pane_bridge = _PaneBridge()
    app = _WsApp(sessions_view, pane_bridge)
    session = SessionDTO(session_id="session-1", title="title", status="idle", computer="c1")

    app._handle_ws_event(SessionStartedEvent(event="session_started", data=session))

    assert len(app._post_messages) == 1
    assert type(app._post_messages[0]).__name__ == "SessionStarted"
    assert app._post_messages[0].session.session_id == "session-1"


@pytest.mark.unit
def test_on_agent_activity_strips_duplicate_tool_name_prefix_from_preview() -> None:
    sessions_view = _SessionsView()
    pane_bridge = _PaneBridge()
    app = _WsApp(sessions_view, pane_bridge)
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
def test_on_session_closed_drops_cached_agent_and_updates_views() -> None:
    sessions_view = _SessionsView()
    pane_bridge = _PaneBridge()
    app = _WsApp(sessions_view, pane_bridge)

    app.on_session_closed(SessionClosed("session-1"))

    assert app._session_agents == {}
    assert sessions_view.closed == ["session-1"]
    assert pane_bridge.removed_sessions == ["session-1"]
    # No _refresh_data — optimistic update from event payload
    app._refresh_data.assert_not_called()


@pytest.mark.unit
def test_on_session_started_updates_bridge_and_view_optimistically() -> None:
    sessions_view = _SessionsView()
    pane_bridge = _PaneBridge()
    app = _WsApp(sessions_view, pane_bridge)
    session = SessionDTO(
        session_id="session-2",
        title="new",
        status="idle",
        computer="c1",
        active_agent="claude",
        initiator_session_id="parent-1",
    )

    from teleclaude.cli.tui.messages import SessionStarted

    app.on_session_started(SessionStarted(session))

    assert app._session_agents["session-2"] == "claude"
    assert len(pane_bridge.updated_sessions) == 1
    assert pane_bridge.updated_sessions[0].session_id == "session-2"
    assert len(sessions_view.updated) == 1
    # No _refresh_data — optimistic update from event payload
    app._refresh_data.assert_not_called()


@pytest.mark.unit
def test_on_session_updated_updates_bridge_catalog() -> None:
    sessions_view = _SessionsView()
    pane_bridge = _PaneBridge()
    app = _WsApp(sessions_view, pane_bridge)
    session = SessionDTO(
        session_id="session-1",
        title="updated",
        status="active",
        computer="c1",
        active_agent="claude",
        tmux_session_name="tc_session1",
    )

    from teleclaude.cli.tui.messages import SessionUpdated

    app.on_session_updated(SessionUpdated(session))

    assert len(pane_bridge.updated_sessions) == 1
    assert pane_bridge.updated_sessions[0].tmux_session_name == "tc_session1"
    assert len(sessions_view.updated) == 1
    assert sessions_view.pending_applied == 1
