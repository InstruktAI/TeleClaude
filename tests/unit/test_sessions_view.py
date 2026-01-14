"""Unit tests for SessionsView activity tracking and pane toggling."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.cli.tui.app import FocusContext
from teleclaude.cli.tui.tree import TreeNode
from teleclaude.cli.tui.views.sessions import SessionsView


@dataclass
class DummyPaneManager:
    """Capture toggle_session arguments without tmux interaction."""

    last_args: tuple[object, ...] | None = None

    def toggle_session(self, *args: object) -> None:
        """Record arguments from toggle_session."""
        self.last_args = args

    @property
    def active_session(self) -> str | None:
        """No active session tracking for tests."""
        return None


def test_update_activity_state_marks_idle_when_activity_is_old():
    """Test that sessions with stale activity are marked idle."""
    fixed_now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    class FixedDatetime(datetime):
        """Datetime shim returning a fixed current time."""

        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            return fixed_now if tz else fixed_now.replace(tzinfo=None)

        @classmethod
        def fromisoformat(cls, date_string: str) -> datetime:
            return datetime.fromisoformat(date_string)

    view = SessionsView(api=object(), agent_availability={}, focus=FocusContext(), pane_manager=DummyPaneManager())
    old_activity = (fixed_now.replace(tzinfo=timezone.utc) - timedelta(seconds=61)).isoformat()
    sessions = [
        {
            "session_id": "sess-1",
            "last_input": "hello",
            "last_output": "world",
            "last_activity": old_activity,
        }
    ]

    with patch("teleclaude.cli.tui.views.sessions.datetime", FixedDatetime):
        view._update_activity_state(sessions)

    assert view._active_field["sess-1"] == "none"


def test_update_activity_state_tracks_output_input_and_idle():
    """Test that output then input changes update active_field until idle."""
    fixed_now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    class FixedDatetime(datetime):
        """Datetime shim returning a fixed current time."""

        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            return fixed_now if tz else fixed_now.replace(tzinfo=None)

        @classmethod
        def fromisoformat(cls, date_string: str) -> datetime:
            return datetime.fromisoformat(date_string)

    view = SessionsView(api=object(), agent_availability={}, focus=FocusContext(), pane_manager=DummyPaneManager())
    recent_activity = fixed_now.isoformat()
    sessions = [
        {
            "session_id": "sess-1",
            "last_input": "",
            "last_output": "out-1",
            "last_activity": recent_activity,
        }
    ]

    with patch("teleclaude.cli.tui.views.sessions.datetime", FixedDatetime):
        view._update_activity_state(sessions)
        assert view._active_field["sess-1"] == "output"

        sessions[0]["last_input"] = "in-1"
        view._update_activity_state(sessions)
        assert view._active_field["sess-1"] == "input"

        sessions[0]["last_activity"] = (fixed_now - timedelta(seconds=90)).isoformat()
        view._update_activity_state(sessions)

    assert view._active_field["sess-1"] == "none"


def test_update_activity_state_handles_naive_timestamp():
    """Test that naive timestamps are treated as UTC when evaluating idle state."""
    fixed_now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    class FixedDatetime(datetime):
        """Datetime shim returning a fixed current time."""

        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            return fixed_now if tz else fixed_now.replace(tzinfo=None)

        @classmethod
        def fromisoformat(cls, date_string: str) -> datetime:
            return datetime.fromisoformat(date_string)

    view = SessionsView(api=object(), agent_availability={}, focus=FocusContext(), pane_manager=DummyPaneManager())
    naive_activity = (fixed_now - timedelta(seconds=10)).replace(tzinfo=None).isoformat()
    sessions = [
        {
            "session_id": "sess-2",
            "last_input": "",
            "last_output": "output",
            "last_activity": naive_activity,
        }
    ]

    with patch("teleclaude.cli.tui.views.sessions.datetime", FixedDatetime):
        view._update_activity_state(sessions)

    assert view._active_field["sess-2"] == "output"


def test_toggle_session_pane_passes_child_session_and_computer_info():
    """Test that _toggle_session_pane uses initiator_session_id for child lookup."""
    pane_manager = DummyPaneManager()
    view = SessionsView(api=object(), agent_availability={}, focus=FocusContext(), pane_manager=pane_manager)
    view._sessions = [
        {"session_id": "parent", "tmux_session_name": "tmux-parent", "computer": "remote"},
        {"session_id": "child", "tmux_session_name": "tmux-child", "initiator_session_id": "parent"},
    ]
    view._computers = [{"name": "remote", "user": "user", "host": "host.example"}]

    item = TreeNode(
        type="session",
        data={"session_id": "parent", "tmux_session_name": "tmux-parent", "computer": "remote"},
        depth=0,
    )

    view._toggle_session_pane(item)

    assert pane_manager.last_args is not None
    tmux_session, child_session, computer_info = pane_manager.last_args
    assert tmux_session == "tmux-parent"
    assert child_session == "tmux-child"
    assert computer_info is not None
    assert computer_info.name == "remote"
    assert computer_info.is_remote is True


def test_toggle_session_pane_skips_when_tmux_session_missing():
    """Test that _toggle_session_pane returns without toggling when tmux name is missing."""
    pane_manager = DummyPaneManager()
    view = SessionsView(api=object(), agent_availability={}, focus=FocusContext(), pane_manager=pane_manager)
    view._sessions = []
    view._computers = []

    item = TreeNode(type="session", data={"session_id": "parent"}, depth=0)

    view._toggle_session_pane(item)

    assert pane_manager.last_args is None
