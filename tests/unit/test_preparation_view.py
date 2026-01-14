"""Unit tests for PreparationView session launch behavior."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import Mock, patch

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.cli.tui.app import FocusContext
from teleclaude.cli.tui.views.preparation import PreparationView


class DummyAPI:
    """API stub for create_session calls."""

    def __init__(self, result: dict[str, object]) -> None:  # guard: loose-dict - test fixture payloads
        self._result = result
        self.calls: list[dict[str, object]] = []  # guard: loose-dict - test fixture payloads

    async def create_session(self, **kwargs: object) -> dict[str, object]:  # guard: loose-dict - test fixture payloads
        """Return the preconfigured result."""
        self.calls.append(kwargs)
        return self._result


class DummyScreen:
    """Curses screen stub."""

    def __init__(self) -> None:
        self.refresh_called = False

    def refresh(self) -> None:
        """Record refresh calls."""
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


def test_launch_session_split_returns_when_tmux_session_missing():
    """Test that _launch_session_split exits when no tmux session name is returned."""
    api = DummyAPI(result={})
    view = PreparationView(api=api, agent_availability={}, focus=FocusContext())
    screen = DummyScreen()

    with (
        patch.dict("os.environ", {"TMUX": "1"}),
        patch("teleclaude.cli.tui.views.preparation.subprocess.run") as mock_run,
    ):
        with (
            patch("teleclaude.cli.tui.views.preparation.curses.def_prog_mode") as mock_def,
            patch("teleclaude.cli.tui.views.preparation.curses.endwin") as mock_end,
            patch("teleclaude.cli.tui.views.preparation.curses.reset_prog_mode") as mock_reset,
        ):
            _run_with_loop(
                lambda: view._launch_session_split({"computer": "local", "project_path": "/tmp"}, "hi", screen)
            )

    assert mock_run.call_count == 0
    assert mock_def.call_count == 0
    assert mock_end.call_count == 0
    assert mock_reset.call_count == 0
    assert screen.refresh_called is False


def test_launch_session_split_splits_tmux_and_restores_curses():
    """Test that _launch_session_split splits tmux and restores curses when in tmux."""
    api = DummyAPI(result={"tmux_session_name": "session-1"})
    view = PreparationView(api=api, agent_availability={}, focus=FocusContext())
    screen = DummyScreen()

    mock_run = Mock()
    with (
        patch.dict("os.environ", {"TMUX": "1"}),
        patch("teleclaude.cli.tui.views.preparation.subprocess.run", mock_run),
        patch("teleclaude.cli.tui.views.preparation.curses.def_prog_mode") as mock_def,
        patch("teleclaude.cli.tui.views.preparation.curses.endwin") as mock_end,
        patch("teleclaude.cli.tui.views.preparation.curses.reset_prog_mode") as mock_reset,
    ):
        _run_with_loop(lambda: view._launch_session_split({"computer": "local", "project_path": "/tmp"}, "hi", screen))

    assert mock_def.call_count == 1
    assert mock_end.call_count == 1
    assert mock_reset.call_count == 1
    assert screen.refresh_called is True
    assert mock_run.call_count == 1
    assert "split-window" in mock_run.call_args[0][0]


def test_launch_session_split_skips_tmux_when_not_inside_tmux():
    """Test that _launch_session_split does not invoke tmux outside of tmux."""
    api = DummyAPI(result={"tmux_session_name": "session-1"})
    view = PreparationView(api=api, agent_availability={}, focus=FocusContext())
    screen = DummyScreen()

    with (
        patch.dict("os.environ", {}, clear=True),
        patch("teleclaude.cli.tui.views.preparation.subprocess.run") as mock_run,
    ):
        _run_with_loop(lambda: view._launch_session_split({"computer": "local", "project_path": "/tmp"}, "hi", screen))

    assert mock_run.call_count == 0
    assert screen.refresh_called is False
