"""Unit tests for SessionsView activity tracking and pane toggling."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from unittest.mock import AsyncMock, Mock

import pytest

from teleclaude.cli.models import ComputerInfo, SessionInfo
from teleclaude.cli.tui.app import FocusContext
from teleclaude.cli.tui.tree import SessionDisplayInfo, SessionNode
from teleclaude.cli.tui.types import ActivePane
from teleclaude.cli.tui.views.sessions import SessionsView


@dataclass
class DummyPaneManager:
    """Capture toggle_session arguments without tmux interaction."""

    last_args: tuple[object, ...] | None = None
    is_available: bool = True
    apply_called: bool = False

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

    view = SessionsView(api=AsyncMock(), agent_availability={}, focus=FocusContext(), pane_manager=DummyPaneManager())
    old_activity = (fixed_now - timedelta(seconds=61)).isoformat()

    sessions = [
        SessionInfo(
            session_id="sess-1",
            last_input_origin="telegram",
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
    view = SessionsView(api=api, agent_availability={}, focus=FocusContext(), pane_manager=pane_manager)

    # Setup state needed for toggle
    session = SessionInfo(
        session_id="parent",
        last_input_origin="telegram",
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
        last_input_origin="telegram",
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

    assert pane_manager.apply_called is True
