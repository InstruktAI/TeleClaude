"""Tests for TUI resource leak fixes — timer and task lifecycle management.

Covers the debounce-and-cancel patterns introduced to prevent untracked
asyncio tasks and Textual timers from leaking on repeated invocation
or during shutdown.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from teleclaude.cli.tui import app_media

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MediaApp(app_media.TelecAppMediaMixin):
    """Minimal host for testing the real _schedule/_cancel chiptunes methods."""

    def __init__(self) -> None:
        self._chiptunes_reconcile_task: asyncio.Task[None] | None = None
        self.api = SimpleNamespace(
            get_chiptunes_status=AsyncMock(
                return_value=SimpleNamespace(
                    loaded=True,
                    playback="playing",
                    state_version=1,
                    playing=True,
                    track="test",
                    sid_path="test.sid",
                    pending_command_id="",
                    pending_action="",
                ),
            ),
        )
        self._chiptunes_state_version = 0

    def query_one(self, *_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(
            chiptunes_loaded=True,
            chiptunes_playback="playing",
            chiptunes_playing=True,
            chiptunes_track="test",
            chiptunes_sid_path="test.sid",
            chiptunes_pending_command_id="",
            chiptunes_pending_action="",
            chiptunes_favorited=False,
        )


# ---------------------------------------------------------------------------
# _schedule_chiptunes_reconcile — debounce behavior
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_schedule_chiptunes_reconcile_stores_task_reference() -> None:
    """After scheduling, _chiptunes_reconcile_task must hold a live Task."""
    app = _MediaApp()
    app._schedule_chiptunes_reconcile()
    assert app._chiptunes_reconcile_task is not None
    assert isinstance(app._chiptunes_reconcile_task, asyncio.Task)
    app._chiptunes_reconcile_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await app._chiptunes_reconcile_task


@pytest.mark.unit
@pytest.mark.asyncio
async def test_schedule_chiptunes_reconcile_cancels_previous_task() -> None:
    """Calling schedule twice must cancel the first task (debounce)."""
    app = _MediaApp()
    app._schedule_chiptunes_reconcile()
    first_task = app._chiptunes_reconcile_task
    assert first_task is not None

    app._schedule_chiptunes_reconcile()
    second_task = app._chiptunes_reconcile_task
    assert second_task is not None
    assert second_task is not first_task

    # Let the event loop process the cancellation
    with pytest.raises(asyncio.CancelledError):
        await first_task

    # Cleanup
    second_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second_task


@pytest.mark.unit
@pytest.mark.asyncio
async def test_schedule_chiptunes_reconcile_nulls_task_on_completion() -> None:
    """After the reconcile coroutine completes, the task reference must be None."""
    app = _MediaApp()
    app._schedule_chiptunes_reconcile()
    task = app._chiptunes_reconcile_task
    assert task is not None
    # Let the task complete (0.2s sleep + sync)
    await task
    assert app._chiptunes_reconcile_task is None


# ---------------------------------------------------------------------------
# _cancel_chiptunes_reconcile
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cancel_chiptunes_reconcile_noop_when_none() -> None:
    """Cancel with no active task must be a safe no-op."""
    app = _MediaApp()
    assert app._chiptunes_reconcile_task is None
    app._cancel_chiptunes_reconcile()
    assert app._chiptunes_reconcile_task is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancel_chiptunes_reconcile_cancels_active_task() -> None:
    """Cancel must cancel the active task and null the reference."""
    app = _MediaApp()
    app._schedule_chiptunes_reconcile()
    task = app._chiptunes_reconcile_task
    assert task is not None

    app._cancel_chiptunes_reconcile()
    assert app._chiptunes_reconcile_task is None

    # Let the event loop process the cancellation
    with pytest.raises(asyncio.CancelledError):
        await task


# ---------------------------------------------------------------------------
# _schedule_sky_width_invalidation — debounce behavior
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_schedule_sky_width_invalidation_stores_timer() -> None:
    """After scheduling, _sky_width_timer must hold a timer object."""
    mock_timer = MagicMock()
    app_mock = MagicMock()
    app_mock._sky_width_timer = None
    app_mock.set_timer = Mock(return_value=mock_timer)

    from teleclaude.cli.tui.app import TelecApp

    TelecApp._schedule_sky_width_invalidation(app_mock)
    assert app_mock._sky_width_timer is mock_timer


@pytest.mark.unit
def test_schedule_sky_width_invalidation_stops_previous_timer() -> None:
    """Calling schedule twice must stop the first timer (debounce)."""
    old_timer = MagicMock()
    new_timer = MagicMock()
    app_mock = MagicMock()
    app_mock._sky_width_timer = old_timer
    app_mock.set_timer = Mock(return_value=new_timer)

    from teleclaude.cli.tui.app import TelecApp

    TelecApp._schedule_sky_width_invalidation(app_mock)
    old_timer.stop.assert_called_once()
    assert app_mock._sky_width_timer is new_timer


# ---------------------------------------------------------------------------
# _cancel_sky_width_timer
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cancel_sky_width_timer_noop_when_none() -> None:
    """Cancel with no active timer must be a safe no-op."""
    app_mock = MagicMock()
    app_mock._sky_width_timer = None

    from teleclaude.cli.tui.app import TelecApp

    TelecApp._cancel_sky_width_timer(app_mock)
    assert app_mock._sky_width_timer is None


@pytest.mark.unit
def test_cancel_sky_width_timer_stops_and_nulls() -> None:
    """Cancel must stop the timer and null the reference."""
    timer = MagicMock()
    app_mock = MagicMock()
    app_mock._sky_width_timer = timer

    from teleclaude.cli.tui.app import TelecApp

    TelecApp._cancel_sky_width_timer(app_mock)
    timer.stop.assert_called_once()
    assert app_mock._sky_width_timer is None


# ---------------------------------------------------------------------------
# SessionsView.on_unmount — bulk timer cleanup
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_on_unmount_stops_all_highlight_timers() -> None:
    """on_unmount must stop every highlight timer and clear the dict."""
    timer_a = MagicMock()
    timer_b = MagicMock()

    view_mock = MagicMock()
    view_mock._highlight_timers = {"sess-a": timer_a, "sess-b": timer_b}

    from teleclaude.cli.tui.views.sessions import SessionsView

    SessionsView.on_unmount(view_mock)

    timer_a.stop.assert_called_once()
    timer_b.stop.assert_called_once()
    assert len(view_mock._highlight_timers) == 0


@pytest.mark.unit
def test_on_unmount_noop_when_no_timers() -> None:
    """on_unmount with empty timers dict must be a safe no-op."""
    view_mock = MagicMock()
    view_mock._highlight_timers = {}

    from teleclaude.cli.tui.views.sessions import SessionsView

    SessionsView.on_unmount(view_mock)
    assert len(view_mock._highlight_timers) == 0
