"""Tests for output poller snapshot-driven behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from teleclaude.core.output_poller import OutputChanged, OutputPoller, ProcessExited
from teleclaude.core.tmux_bridge._pane import PaneSnapshot


class TestOutputPoller:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_uses_snapshot_instead_of_separate_tmux_checks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        snapshots = [
            PaneSnapshot(session_exists=True, pane_dead=False, output="hello\n"),
            PaneSnapshot(session_exists=True, pane_dead=True, output="hello\n"),
        ]
        collect_snapshot = AsyncMock(side_effect=snapshots)
        unexpected = AsyncMock(side_effect=AssertionError("legacy tmux helper should not be used"))

        monkeypatch.setattr("teleclaude.core.output_poller.tmux_bridge.collect_pane_snapshot", collect_snapshot)
        monkeypatch.setattr("teleclaude.core.output_poller.tmux_bridge.session_exists", unexpected)
        monkeypatch.setattr("teleclaude.core.output_poller.tmux_bridge.capture_pane", unexpected)
        monkeypatch.setattr("teleclaude.core.output_poller.tmux_bridge.is_pane_dead", unexpected)
        monkeypatch.setattr("teleclaude.core.output_poller.asyncio.sleep", AsyncMock())

        poller = OutputPoller()
        events = [event async for event in poller.poll("session-1", "tmux-alpha", Path("/tmp/output.log"))]

        assert collect_snapshot.await_count == 2
        assert any(isinstance(event, OutputChanged) and event.output == "hello\n" for event in events)
        assert isinstance(events[-1], ProcessExited)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_treats_missing_snapshot_session_as_process_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        collect_snapshot = AsyncMock(return_value=PaneSnapshot(session_exists=False, pane_dead=False, output=""))
        monkeypatch.setattr("teleclaude.core.output_poller.tmux_bridge.collect_pane_snapshot", collect_snapshot)
        monkeypatch.setattr("teleclaude.core.output_poller.asyncio.sleep", AsyncMock())
        monkeypatch.setattr("teleclaude.core.output_poller.db.get_session", AsyncMock(return_value=None))

        poller = OutputPoller()
        events = [event async for event in poller.poll("session-1", "tmux-alpha", Path("/tmp/output.log"))]

        assert collect_snapshot.await_count == 1
        assert len(events) == 1
        assert isinstance(events[0], ProcessExited)
