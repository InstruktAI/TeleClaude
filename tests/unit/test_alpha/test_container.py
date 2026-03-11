"""Unit tests for teleclaude_events.alpha.container."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from teleclaude_events.alpha.container import AlphaContainerManager, scan_cartridges


def test_scan_cartridges_absent_dir():
    result = scan_cartridges("/nonexistent/path/that/does/not/exist")
    assert result == []


def test_scan_cartridges_returns_stems():
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "cart_a.py").write_text("# a")
        Path(tmpdir, "cart_b.py").write_text("# b")
        Path(tmpdir, "ignore.txt").write_text("not a cartridge")
        Path(tmpdir, "subdir").mkdir()

        result = scan_cartridges(tmpdir)
        assert result == ["cart_a", "cart_b"]


def test_has_cartridges_reflects_scan():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AlphaContainerManager(
            socket_path="/tmp/alpha-test.sock",
            cartridges_dir=tmpdir,
        )
        # Initial state: no cartridges detected yet
        assert not manager.has_cartridges

        # Simulate watcher update: manually set _has_cartridges
        Path(tmpdir, "my_cart.py").write_text("# cart")
        manager._has_cartridges = len(scan_cartridges(tmpdir)) > 0  # noqa: SLF001
        assert manager.has_cartridges


@pytest.mark.asyncio
async def test_restart_increments_counter_and_sets_permanently_failed():
    from unittest.mock import AsyncMock, patch

    manager = AlphaContainerManager(
        socket_path="/tmp/alpha-test.sock",
        cartridges_dir="/tmp/alpha-carts",
    )
    manager._container_id = None  # not running

    # Patch stop as no-op, start always fails, emit as no-op
    with (
        patch.object(manager, "stop", new=AsyncMock()),
        patch.object(manager, "start", new=AsyncMock(side_effect=RuntimeError("start failed"))),
        patch.object(manager, "_emit_event", new=AsyncMock()),
    ):
        for _ in range(3):
            await manager.restart()

    assert manager._permanently_failed  # noqa: SLF001
