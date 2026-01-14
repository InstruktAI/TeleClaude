"""Unit tests for PreparationView session launch behavior."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import Mock, patch

import pytest

from teleclaude.cli.tui.app import FocusContext
from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.views.preparation import PreparationView, PrepTodoDisplayInfo, PrepTodoNode


class DummyAPI:
    """API stub for create_session calls."""

    def __init__(self, result: dict[str, object]) -> None:  # guard: loose-dict
        self._result = result

    async def create_session(self, **kwargs: object) -> object:
        from teleclaude.cli.models import CreateSessionResult

        return CreateSessionResult(
            session_id=self._result.get("session_id", "sess-123"),
            tmux_session_name=self._result.get("tmux_session_name"),
            status="success" if self._result.get("tmux_session_name") else "error",
        )


class DummyScreen:
    """Curses screen stub."""

    def __init__(self) -> None:
        self.refresh_called = False

    def refresh(self) -> None:
        self.refresh_called = True


def _run_with_loop(func: callable) -> None:
    """Run a synchronous function with a dedicated event loop."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        func()
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def test_handle_enter_on_ready_todo_splits_tmux_in_tmux_env():
    """Test that handle_enter on a ready todo triggers tmux split when in TMUX."""
    api = DummyAPI(result={"tmux_session_name": "session-1"})
    pane_manager = Mock()
    pane_manager.is_available = False  # Force attach_tmux_from_result / fallback path

    view = PreparationView(api=api, agent_availability={}, focus=FocusContext(), pane_manager=pane_manager)
    screen = DummyScreen()

    view.flat_items = [
        PrepTodoNode(
            type="todo",
            data=PrepTodoDisplayInfo(
                todo=TodoItem(
                    slug="test-todo",
                    status="ready",
                    description="test",
                    has_requirements=True,
                    has_impl_plan=True,
                ),
                project_path="/tmp",
                computer="local",
            ),
            depth=0,
        )
    ]
    view.selected_index = 0

    with (
        patch.dict("os.environ", {"TMUX": "1"}),
        patch("teleclaude.cli.tui.views.preparation.subprocess.run") as mock_run,
        patch("teleclaude.cli.tui.session_launcher.subprocess.run") as mock_launcher_run,
        patch("teleclaude.cli.tui.views.preparation.curses.def_prog_mode") as mock_def,
        patch("teleclaude.cli.tui.views.preparation.curses.endwin") as mock_end,
        patch("teleclaude.cli.tui.views.preparation.curses.reset_prog_mode") as mock_reset,
    ):
        _run_with_loop(lambda: view.handle_enter(screen))

    # Verification: Side effects of session launch
    assert screen.refresh_called is True
    # The actual tmux split happens in session_launcher.attach_tmux_session
    assert mock_launcher_run.call_count == 1
    args = mock_launcher_run.call_args[0][0]
    assert "split-window" in args
    assert "session-1" in args[-1]
