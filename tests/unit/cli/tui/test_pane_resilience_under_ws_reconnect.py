"""Defend TUI preview panes against transient daemon-snapshot inconsistencies.

The TUI must rely on tmux liveness plus explicit `SessionClosed` events for
pane lifecycle — never on snapshot diffs from the daemon. These tests pin the
three paths that previously destroyed panes during a daemon restart.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from teleclaude.api_models import (
    AgentAvailabilityDTO,
    ComputerDTO,
    ProjectDTO,
    SessionDTO,
    SessionsInitialDataDTO,
    SessionsInitialEventDTO,
)
from teleclaude.cli.tui.messages import PreviewChanged, StickyChanged
from teleclaude.cli.tui.pane_manager import TmuxPaneManager
from teleclaude.cli.tui.views.sessions import SessionsView
from tests.unit.cli.tui.test_app_ws import _PaneBridge, _SessionsView, _WsApp


def _session(session_id: str, *, computer: str = "local", tmux: str | None = None) -> SessionDTO:
    return SessionDTO(
        session_id=session_id,
        title=session_id,
        status="active",
        computer=computer,
        tmux_session_name=tmux or f"tc_{session_id}",
    )


class _LogStub:
    def trace(self, *_args: object, **_kwargs: object) -> None: ...
    def info(self, *_args: object, **_kwargs: object) -> None: ...
    def debug(self, *_args: object, **_kwargs: object) -> None: ...


@pytest.mark.unit
def test_update_data_does_not_prune_sticky_or_preview_when_session_absent_from_snapshot() -> None:
    """A bootstrap snapshot missing a sticky/preview session must not destroy state.

    Daemon restart causes a transient WS reconnect; the bootstrap that follows
    may briefly omit sessions whose tmux is still alive. The view must keep its
    sticky/preview state intact and must not post StickyChanged/PreviewChanged
    based on snapshot absence.
    """

    # Stand-in view skips Textual's reactive descriptor on preview_session_id —
    # we test update_data's logic, not Textual's reactive plumbing.
    class _ViewStub:
        update_data = SessionsView.update_data

        def __init__(self) -> None:
            self._computers: list[ComputerDTO] = []
            self._projects: list[ProjectDTO] = []
            self._sessions = [_session("alive-1"), _session("alive-2")]
            self._availability: dict[str, AgentAvailabilityDTO] = {}
            self._optimistically_hidden_session_ids: set[str] = set()
            self._sticky_session_ids = ["alive-1"]
            self.preview_session_id: str | None = "alive-2"
            self._nav_items: list[object] = []
            self._last_output_summary: dict[str, str] = {}
            self.posted: list[object] = []
            self._logger = _LogStub()
            self._rebuild_tree = Mock()
            self._apply_pending_selection = Mock()
            self._notify_state_changed = Mock()

        def post_message(self, message: object) -> None:
            self.posted.append(message)

    view = _ViewStub()

    # Snapshot omits both sticky and preview — simulating a transient daemon view.
    view.update_data(computers=[], projects=[], sessions=[])

    assert view._sticky_session_ids == ["alive-1"], "sticky state must survive a transient empty snapshot"
    assert view.preview_session_id == "alive-2", "preview state must survive a transient empty snapshot"
    assert not any(isinstance(m, StickyChanged) for m in view.posted), "no StickyChanged on snapshot diff"
    assert not any(isinstance(m, PreviewChanged) for m in view.posted), "no PreviewChanged on snapshot diff"


@pytest.mark.unit
def test_update_session_catalog_retains_entries_for_sessions_referenced_by_active_state() -> None:
    """Catalog merge must retain entries for sticky/active sessions absent from the new list.

    `update_session_catalog` is fed by every WS refresh. Wholesale replacement
    drops entries the layout depends on, which causes `_build_sticky_specs` to
    skip them and triggers a destructive layout re-render. Sessions referenced
    by sticky or active specs must be preserved across the call.
    """
    manager = object.__new__(TmuxPaneManager)
    sticky_session = _session("sticky-1")
    preview_session = _session("preview-1")
    other_session = _session("other-1")
    manager._session_catalog = {
        "sticky-1": sticky_session,
        "preview-1": preview_session,
        "other-1": other_session,
    }
    manager._layout_state = SimpleNamespace(
        sticky_specs=[SimpleNamespace(session_id="sticky-1")],
        active_spec=SimpleNamespace(session_id="preview-1"),
    )

    # New snapshot only carries one session; sticky and preview are absent.
    manager.update_session_catalog([_session("brand-new")])

    assert "sticky-1" in manager._session_catalog, "sticky-referenced session must be retained"
    assert "preview-1" in manager._session_catalog, "active-referenced session must be retained"
    assert "brand-new" in manager._session_catalog, "new session must be added"
    assert "other-1" not in manager._session_catalog, "unreferenced session must be replaced"


@pytest.mark.unit
def test_sessions_initial_event_merges_per_computer_instead_of_overwriting() -> None:
    """A SessionsInitialEvent for one computer must not wipe sessions from another.

    On WS reconnect each subscribed computer fires its own SessionsInitialEvent.
    Overwriting the full session list with one computer's sessions causes the
    other computers' sticky/active sessions to disappear and panes to die.
    """
    sessions_view = _SessionsView()
    sessions_view._computers = [
        ComputerDTO(name="local", status="online", user="me", host="local", is_local=True),
        ComputerDTO(name="remote", status="online", user="me", host="remote", is_local=False),
    ]
    sessions_view._projects = [ProjectDTO(computer="local", name="p", path="/p")]
    sessions_view._sessions = [_session("local-1", computer="local"), _session("remote-1", computer="remote")]
    sessions_view._availability = {"claude": AgentAvailabilityDTO(agent="claude", available=True, status="available")}

    app = _WsApp(sessions_view, _PaneBridge())

    # Initial event for "local" arrives carrying only local sessions.
    app._handle_ws_event(
        SessionsInitialEventDTO(
            data=SessionsInitialDataDTO(
                sessions=[_session("local-1", computer="local")],
                computer="local",
            )
        )
    )

    session_ids = {s.session_id for s in sessions_view._sessions}
    assert "local-1" in session_ids, "local sessions from this event must be present"
    assert "remote-1" in session_ids, "sessions from other computers must not be wiped by a per-computer event"
