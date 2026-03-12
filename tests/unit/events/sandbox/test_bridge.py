"""Unit tests for teleclaude.events.sandbox.bridge."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.events.sandbox.bridge import SandboxBridgeCartridge
from teleclaude.events.sandbox.container import SandboxContainerManager
from teleclaude.events.sandbox.protocol import FrameTooLargeError
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility


def _make_event() -> EventEnvelope:
    return EventEnvelope(
        event="test.event",
        source="test",
        level=EventLevel.OPERATIONAL,
        domain="test",
        description="test event",
        visibility=EventVisibility.LOCAL,
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def _make_manager(has_cartridges: bool = True) -> SandboxContainerManager:
    manager = MagicMock(spec=SandboxContainerManager)
    manager.has_cartridges = has_cartridges
    manager.permanently_failed = False
    manager.docker_unavailable = False
    manager.cartridges_dir = "/tmp/sandbox-carts"
    manager.socket_path = "/tmp/sandbox-test.sock"
    return manager


@pytest.mark.asyncio
async def test_fast_path_no_cartridges():
    """Bridge skips processing when manager has no cartridges."""
    manager = _make_manager(has_cartridges=False)
    bridge = SandboxBridgeCartridge(manager=manager)
    event = _make_event()
    result = await bridge.process(event, MagicMock())
    assert result is event
    assert "_sandbox_results" not in event.payload


@pytest.mark.asyncio
async def test_fast_path_permanently_failed():
    """Bridge skips processing when manager is permanently failed."""
    manager = _make_manager(has_cartridges=True)
    manager.permanently_failed = True
    bridge = SandboxBridgeCartridge(manager=manager)
    event = _make_event()
    result = await bridge.process(event, MagicMock())
    assert result is event
    assert "_sandbox_results" not in event.payload


@pytest.mark.asyncio
async def test_fast_path_docker_unavailable():
    """Bridge skips processing when Docker is unavailable."""
    manager = _make_manager(has_cartridges=True)
    manager.docker_unavailable = True
    bridge = SandboxBridgeCartridge(manager=manager)
    event = _make_event()
    result = await bridge.process(event, MagicMock())
    assert result is event
    assert "_sandbox_results" not in event.payload


@pytest.mark.asyncio
async def test_attaches_sandbox_results_on_success():
    """Bridge attaches cartridge results to event payload on successful invocation."""
    manager = _make_manager(has_cartridges=True)
    bridge = SandboxBridgeCartridge(manager=manager)
    event = _make_event()

    response_dict = {"envelope": None, "error": None, "duration_ms": 5.0}

    context = MagicMock()
    context.catalog.list_all.return_value = []

    with (
        patch("teleclaude.events.sandbox.bridge.scan_cartridges", return_value=["echo_cart"]),
        patch("asyncio.open_unix_connection", new=AsyncMock()) as mock_conn,
        patch("teleclaude.events.sandbox.bridge.write_frame", new=AsyncMock()),
        patch("teleclaude.events.sandbox.bridge.read_frame", new=AsyncMock(return_value=response_dict)),
    ):
        mock_writer = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        mock_conn.return_value = (AsyncMock(), mock_writer)

        result = await bridge.process(event, context)

    assert result is event
    assert "_sandbox_results" in result.payload
    assert len(result.payload["_sandbox_results"]) == 1
    assert result.payload["_sandbox_results"][0]["cartridge"] == "echo_cart"


@pytest.mark.asyncio
async def test_timeout_produces_error_entry():
    """TimeoutError during cartridge invocation produces an error entry, never propagates."""
    manager = _make_manager(has_cartridges=True)
    bridge = SandboxBridgeCartridge(manager=manager)
    event = _make_event()

    context = MagicMock()
    context.catalog.list_all.return_value = []

    with (
        patch("teleclaude.events.sandbox.bridge.scan_cartridges", return_value=["slow_cart"]),
        patch("asyncio.open_unix_connection", side_effect=asyncio.TimeoutError),
    ):
        result = await bridge.process(event, context)

    assert result is event
    assert "_sandbox_results" in result.payload
    assert result.payload["_sandbox_results"][0]["error"] == "timeout"


@pytest.mark.asyncio
async def test_connection_error_produces_error_entry():
    """ConnectionRefusedError during cartridge invocation produces an error entry, never propagates."""
    manager = _make_manager(has_cartridges=True)
    bridge = SandboxBridgeCartridge(manager=manager)
    event = _make_event()

    context = MagicMock()
    context.catalog.list_all.return_value = []

    with (
        patch("teleclaude.events.sandbox.bridge.scan_cartridges", return_value=["conn_cart"]),
        patch("asyncio.open_unix_connection", side_effect=ConnectionRefusedError("refused")),
    ):
        result = await bridge.process(event, context)

    assert result is event
    assert result.payload["_sandbox_results"][0]["error"] == "unavailable"


@pytest.mark.asyncio
async def test_frame_too_large_produces_error_entry():
    """FrameTooLargeError during cartridge response produces an error entry, never propagates."""
    manager = _make_manager(has_cartridges=True)
    bridge = SandboxBridgeCartridge(manager=manager)
    event = _make_event()

    context = MagicMock()
    context.catalog.list_all.return_value = []

    with (
        patch("teleclaude.events.sandbox.bridge.scan_cartridges", return_value=["big_cart"]),
        patch("asyncio.open_unix_connection", new=AsyncMock()) as mock_conn,
        patch("teleclaude.events.sandbox.bridge.write_frame", new=AsyncMock()),
        patch("teleclaude.events.sandbox.bridge.read_frame", side_effect=FrameTooLargeError("too big")),
    ):
        mock_writer = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        mock_conn.return_value = (AsyncMock(), mock_writer)

        result = await bridge.process(event, context)

    assert result is event
    assert result.payload["_sandbox_results"][0]["error"] == "frame_too_large"


@pytest.mark.asyncio
async def test_outer_catch_all_returns_event_on_exception():
    """When _process raises unexpectedly, process() still returns the event — never blocks the pipeline."""
    manager = _make_manager(has_cartridges=True)
    bridge = SandboxBridgeCartridge(manager=manager)
    event = _make_event()

    with patch.object(bridge, "_process", side_effect=RuntimeError("kaboom")):
        result = await bridge.process(event, MagicMock())

    assert result is event
