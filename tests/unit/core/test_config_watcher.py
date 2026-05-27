"""Tests for the daemon config-file watcher."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from teleclaude.core.config_watcher import ConfigWatcher

pytestmark = [pytest.mark.unit]


def _bump_mtime(path: Path) -> None:
    future = time.time() + 10
    os.utime(path, (future, future))


@pytest.mark.unit
def test_changed_is_false_until_a_watched_file_changes(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yml"
    cfg.write_text("a: 1\n", encoding="utf-8")

    async def _noop() -> None: ...

    watcher = ConfigWatcher([cfg], _noop)

    assert watcher._changed() is False
    _bump_mtime(cfg)
    assert watcher._changed() is True
    # Snapshot advanced — the same change is not reported twice.
    assert watcher._changed() is False


@pytest.mark.unit
def test_changed_detects_a_newly_created_watched_file(tmp_path: Path) -> None:
    missing = tmp_path / ".env"  # absent at construction

    async def _noop() -> None: ...

    watcher = ConfigWatcher([missing], _noop)

    assert watcher._changed() is False
    missing.write_text("X=1\n", encoding="utf-8")
    assert watcher._changed() is True


@pytest.mark.unit
async def test_run_invokes_handler_when_a_watched_file_changes(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yml"
    cfg.write_text("a: 1\n", encoding="utf-8")
    fired = asyncio.Event()

    async def _on_change() -> None:
        fired.set()

    watcher = ConfigWatcher([cfg], _on_change, poll_interval_s=0.01)
    task = asyncio.create_task(watcher.run())
    try:
        await asyncio.sleep(0.03)
        _bump_mtime(cfg)
        await asyncio.wait_for(fired.wait(), timeout=1.0)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert fired.is_set()
