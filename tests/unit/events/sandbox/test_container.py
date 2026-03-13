"""Unit tests for teleclaude.events.sandbox.container."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from teleclaude.events.sandbox.container import SandboxContainerManager, scan_cartridges


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


@pytest.mark.asyncio
async def test_restart_increments_counter_and_sets_permanently_failed():
    from unittest.mock import AsyncMock, patch

    manager = SandboxContainerManager(
        socket_path="/tmp/sandbox-test.sock",
        cartridges_dir="/tmp/sandbox-carts",
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

    assert manager._permanently_failed
