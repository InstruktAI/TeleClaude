# pylint: disable=protected-access,too-many-instance-attributes,use-implicit-booleaness-not-comparison,import-outside-toplevel,duplicate-code
from __future__ import annotations

from unittest.mock import Mock

import pytest

from teleclaude.api_models import AgentAvailabilityDTO, AgentAvailabilityEventDTO, SessionDTO, SessionStartedEventDTO
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
        self._availability: dict[str, AgentAvailabilityDTO] = {}
        self.pending_applied: int = 0
        self.select_requests: list[tuple[str, bool]] = []

    def update_activity(self, session_id: str, activity_type: str, detail: str | None = None) -> None:
        self.activity_calls.append((session_id, activity_type, detail))

    def confirm_session_closed(self, session_id: str) -> None:
        self.closed.append(session_id)

    def update_session(self, session: object) -> None:
        self.updated.append(session)

    def request_select_session(self, session_id: str, request_focus: bool = False) -> None:
        self.select_requests.append((session_id, request_focus))

    def _apply_pending_selection(self) -> None:
        self.pending_applied += 1


class _Tabs:
    def __init__(self, active: str = "sessions") -> None:
        self.active = active


class _Footer:
    def __init__(self) -> None:
        self.updated_availability: list[dict[str, AgentAvailabilityDTO]] = []

    def update_availability(self, availability: dict[str, AgentAvailabilityDTO]) -> None:
        self.updated_availability.append(availability)


class _PreparationView:
    def __init__(self) -> None:
        self._availability: dict[str, AgentAvailabilityDTO] = {}


class _WsApp(app_ws.TelecAppWsMixin):
    def __init__(
        self,
        sessions_view: _SessionsView,
        pane_bridge: _PaneBridge,
        *,
        tabs: _Tabs | None = None,
        footer: _Footer | None = None,
        preparation_view: _PreparationView | None = None,
    ) -> None:
        self._sessions_view = sessions_view
        self._pane_bridge = pane_bridge
        self._tabs = tabs or _Tabs()
        self._footer = footer or _Footer()
        self._preparation_view = preparation_view or _PreparationView()
        self._post_messages: list[object] = []
        self._session_agents = {"session-1": "codex"}
        self._availability: dict[str, AgentAvailabilityDTO] = {}
        self._tui_initiated_sessions: set[str] = set()
        self._activity_trigger = None
        self.notify = Mock()
        self._refresh_data = Mock()

    def query_one(self, selector: str, *_args: object) -> object:
        if selector == "#sessions-view":
            return self._sessions_view
        if selector == "#pane-bridge":
            return self._pane_bridge
        if selector == "#main-tabs":
            return self._tabs
        if selector == "#telec-footer":
            return self._footer
        if selector == "#preparation-view":
            return self._preparation_view
        raise AssertionError(selector)

    def post_message(self, message: object) -> None:
        self._post_messages.append(message)


@pytest.mark.unit
def test_handle_ws_event_posts_session_started_messages() -> None:
    sessions_view = _SessionsView()
    pane_bridge = _PaneBridge()
    app = _WsApp(sessions_view, pane_bridge)
    session = SessionDTO(session_id="session-1", title="title", status="idle", computer="c1")

    app._handle_ws_event(SessionStartedEventDTO(event="session_started", data=session))

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
def test_on_agent_activity_passes_thinking_text_through() -> None:
    sessions_view = _SessionsView()
    pane_bridge = _PaneBridge()
    app = _WsApp(sessions_view, pane_bridge)
    message = AgentActivity(
        session_id="session-1",
        activity_type="thinking",
        canonical_type="agent_output_update",
        text="• Working",
    )

    app.on_agent_activity(message)

    assert sessions_view.activity_calls == [("session-1", "thinking", "• Working")]


@pytest.mark.unit
def test_handle_ws_event_updates_live_agent_availability() -> None:
    sessions_view = _SessionsView()
    pane_bridge = _PaneBridge()
    footer = _Footer()
    preparation_view = _PreparationView()
    app = _WsApp(sessions_view, pane_bridge, footer=footer, preparation_view=preparation_view)

    app._handle_ws_event(
        AgentAvailabilityEventDTO(
            data=AgentAvailabilityDTO(
                agent="codex",
                available=False,
                status="unavailable",
                unavailable_until="2026-04-02T12:00:00Z",
            )
        )
    )

    assert app._availability["codex"].status == "unavailable"
    assert footer.updated_availability[-1]["codex"].status == "unavailable"
    assert sessions_view._availability["codex"].status == "unavailable"
    assert preparation_view._availability["codex"].status == "unavailable"


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


@pytest.mark.unit
def test_on_session_started_daemon_spawned_session_does_not_auto_focus() -> None:
    """Sessions not created by the TUI must not steal focus."""
    sessions_view = _SessionsView()
    pane_bridge = _PaneBridge()
    app = _WsApp(sessions_view, pane_bridge, tabs=_Tabs(active="sessions"))
    # Daemon-spawned integrator: not in _tui_initiated_sessions
    session = SessionDTO(
        session_id="integrator-1",
        title="/next-integrate",
        status="idle",
        computer="c1",
        active_agent="claude",
        system_role="integrator",
        job="integrator",
    )

    from teleclaude.cli.tui.messages import SessionStarted

    app.on_session_started(SessionStarted(session))

    assert len(sessions_view.updated) == 1
    assert sessions_view.select_requests == []
    assert sessions_view.pending_applied == 0


@pytest.mark.unit
def test_on_session_started_user_initiated_session_auto_focuses() -> None:
    """Sessions created by the TUI should auto-focus."""
    sessions_view = _SessionsView()
    pane_bridge = _PaneBridge()
    app = _WsApp(sessions_view, pane_bridge, tabs=_Tabs(active="sessions"))
    # TUI-created session: registered in _tui_initiated_sessions
    app._tui_initiated_sessions.add("user-session-1")
    session = SessionDTO(
        session_id="user-session-1",
        title="my session",
        status="idle",
        computer="c1",
        active_agent="claude",
    )

    from teleclaude.cli.tui.messages import SessionStarted

    app.on_session_started(SessionStarted(session))

    assert sessions_view.select_requests == [("user-session-1", True)]
    assert sessions_view.pending_applied == 1
    # Session ID should be removed from tracking set after focus
    assert "user-session-1" not in app._tui_initiated_sessions


@pytest.mark.unit
def test_on_session_started_user_run_session_with_job_auto_focuses() -> None:
    """User-initiated run-session (with job metadata) should auto-focus when TUI-tracked."""
    sessions_view = _SessionsView()
    pane_bridge = _PaneBridge()
    app = _WsApp(sessions_view, pane_bridge, tabs=_Tabs(active="sessions"))
    # Simulate: user started a run-session via TUI that has a job role
    app._tui_initiated_sessions.add("run-session-1")
    session = SessionDTO(
        session_id="run-session-1",
        title="/next-integrate",
        status="idle",
        computer="c1",
        active_agent="claude",
        system_role="integrator",
        job="integrator",
    )

    from teleclaude.cli.tui.messages import SessionStarted

    app.on_session_started(SessionStarted(session))

    # Should auto-focus because the TUI initiated it, despite having job metadata
    assert sessions_view.select_requests == [("run-session-1", True)]
    assert sessions_view.pending_applied == 1
