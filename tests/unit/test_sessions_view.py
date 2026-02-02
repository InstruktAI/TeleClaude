"""Unit tests for SessionsView activity tracking and pane toggling."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from teleclaude.core.origins import InputOrigin

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from unittest.mock import AsyncMock, Mock

import pytest

from teleclaude.cli.models import ComputerInfo, ProjectInfo, SessionInfo
from teleclaude.cli.tui.app import FocusContext
from teleclaude.cli.tui.controller import TuiController
from teleclaude.cli.tui.state import TuiState
from teleclaude.cli.tui.tree import ProjectNode, SessionDisplayInfo, SessionNode
from teleclaude.cli.tui.types import ActivePane, NodeType
from teleclaude.cli.tui.views.sessions import SessionsView


@dataclass
class _DummyPaneState:
    sticky_pane_ids: list[str] | None = None

    def __post_init__(self) -> None:
        if self.sticky_pane_ids is None:
            self.sticky_pane_ids = []


@dataclass
class DummyPaneManager:
    """Capture toggle_session arguments without tmux interaction."""

    last_args: tuple[object, ...] | None = None
    is_available: bool = True
    apply_called: bool = False
    state: _DummyPaneState | None = None

    def __post_init__(self) -> None:
        if self.state is None:
            self.state = _DummyPaneState()

    def toggle_session(self, *args: object) -> None:
        """Record arguments from toggle_session."""
        self.last_args = args

    def show_session(self, *args: object) -> None:
        """Record arguments from show_session."""
        self.last_args = args

    def apply_layout(self, **_kwargs: object) -> None:
        """No-op layout application for tests."""
        self.apply_called = True

    def focus_pane_for_session(self, session_id: str) -> bool:
        """Mock focus method."""
        return True

    @property
    def active_session(self) -> str | None:
        """No active session tracking for tests."""
        return None


@pytest.mark.asyncio
async def test_refresh_updates_activity_state_marks_idle_when_activity_is_old():
    """Test that refresh correctly updates activity state and marks stale activity as idle."""
    fixed_now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            return fixed_now if tz else fixed_now.replace(tzinfo=None)

        @classmethod
        def fromisoformat(cls, date_string: str) -> datetime:
            return datetime.fromisoformat(date_string)

    state = TuiState()
    controller = TuiController(state, DummyPaneManager(), lambda _name: None)
    view = SessionsView(
        api=AsyncMock(),
        agent_availability={},
        focus=FocusContext(),
        pane_manager=DummyPaneManager(),
        state=state,
        controller=controller,
    )
    old_activity = (fixed_now - timedelta(seconds=61)).isoformat()

    sessions = [
        SessionInfo(
            session_id="sess-1",
            last_input_origin=InputOrigin.TELEGRAM.value,
            status="active",
            computer="local",
            project_path="/tmp",
            last_input="hello",
            last_output="world",
            last_activity=old_activity,
            title="test",
            active_agent="claude",
            thinking_mode="slow",
        )
    ]

    with patch("teleclaude.cli.tui.views.sessions.datetime", FixedDatetime):
        await view.refresh(computers=[], projects=[], sessions=sessions)

    assert view._active_field["sess-1"] == ActivePane.NONE


@pytest.mark.asyncio
async def test_handle_enter_on_session_toggles_pane():
    """Test that handle_enter on a session triggers the preview pane toggle."""
    pane_manager = DummyPaneManager()
    api = AsyncMock()
    state = TuiState()
    controller = TuiController(state, pane_manager, lambda _name: None)
    view = SessionsView(
        api=api,
        agent_availability={},
        focus=FocusContext(),
        pane_manager=pane_manager,
        state=state,
        controller=controller,
    )

    # Setup state needed for toggle
    session = SessionInfo(
        session_id="parent",
        last_input_origin=InputOrigin.TELEGRAM.value,
        status="active",
        tmux_session_name="tmux-parent",
        computer="remote",
        project_path="/tmp",
        title="Parent",
        active_agent="claude",
        thinking_mode="slow",
        initiator_session_id=None,
    )
    child = SessionInfo(
        session_id="child",
        last_input_origin=InputOrigin.TELEGRAM.value,
        status="active",
        tmux_session_name="tmux-child",
        computer="remote",
        project_path="/tmp",
        title="Child",
        active_agent="claude",
        thinking_mode="slow",
        initiator_session_id="parent",
    )

    view._sessions = [session, child]
    view._computers = [
        ComputerInfo(name="remote", status="online", is_local=False, user="user", host="host", role="test")
    ]

    # Create a SessionNode for the flat_items
    item = SessionNode(
        type="session", data=SessionDisplayInfo(session=session, display_index="1"), depth=0, children=[]
    )
    view.flat_items = [item]
    view.selected_index = 0
    screen = Mock()
    view.handle_enter(screen)
    view.apply_pending_activation()
    controller.apply_pending_layout()

    assert pane_manager.apply_called is True


def test_open_project_sessions_sets_sticky_list():
    """Project shortcut should sticky project sessions (up to 5) and apply layout."""
    pane_manager = DummyPaneManager()
    state = TuiState()
    controller = TuiController(state, pane_manager, lambda _name: None)
    view = SessionsView(
        api=AsyncMock(),
        agent_availability={},
        focus=FocusContext(),
        pane_manager=pane_manager,
        state=state,
        controller=controller,
    )

    project = ProjectInfo(computer="local", name="TeleClaude", path="/repo")
    sessions = [
        SessionInfo(
            session_id="sess-0",
            last_input_origin=InputOrigin.TELEGRAM.value,
            status="active",
            tmux_session_name="tmux-0",
            computer="local",
            project_path="/repo",
            title="Session 0",
            active_agent="claude",
            thinking_mode="slow",
        ),
        SessionInfo(
            session_id="sess-1",
            last_input_origin=InputOrigin.TELEGRAM.value,
            status="active",
            tmux_session_name="tmux-1",
            computer="local",
            project_path="/repo",
            title="Session 1",
            active_agent="claude",
            thinking_mode="slow",
        ),
        SessionInfo(
            session_id="sess-2",
            last_input_origin=InputOrigin.TELEGRAM.value,
            status="active",
            tmux_session_name="tmux-2",
            computer="local",
            project_path="/repo",
            title="Session 2",
            active_agent="claude",
            thinking_mode="slow",
        ),
    ]

    view._sessions = list(reversed(sessions))
    view.flat_items = [
        ProjectNode(type=NodeType.PROJECT, data=project, depth=0, children=[]),
        SessionNode(type=NodeType.SESSION, data=SessionDisplayInfo(session=sessions[2], display_index="1"), depth=1),
        SessionNode(type=NodeType.SESSION, data=SessionDisplayInfo(session=sessions[0], display_index="2"), depth=1),
        SessionNode(type=NodeType.SESSION, data=SessionDisplayInfo(session=sessions[1], display_index="3"), depth=1),
    ]
    view.selected_index = 0

    view.handle_key(ord("a"), Mock())

    assert pane_manager.apply_called is True
    assert [sticky.session_id for sticky in view.sticky_sessions] == ["sess-2", "sess-0", "sess-1"]
