"""Unit tests for teleclaude_events.alpha.bridge."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude_events.alpha.bridge import AlphaBridgeCartridge
from teleclaude_events.alpha.container import AlphaContainerManager
from teleclaude_events.envelope import EventEnvelope, EventLevel, EventVisibility


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


def _make_manager(has_cartridges: bool = True) -> AlphaContainerManager:
    manager = MagicMock(spec=AlphaContainerManager)
    manager.has_cartridges = has_cartridges
    manager.permanently_failed = False
    manager.docker_unavailable = False
    manager.cartridges_dir = "/tmp/alpha-carts"
    manager.socket_path = "/tmp/alpha-test.sock"
    return manager


@pytest.mark.asyncio
async def test_fast_path_no_cartridges():
    manager = _make_manager(has_cartridges=False)
    bridge = AlphaBridgeCartridge(manager=manager)
    event = _make_event()
    result = await bridge.process(event, MagicMock())
    assert result is event
    assert "_alpha_results" not in event.payload


@pytest.mark.asyncio
async def test_fast_path_permanently_failed():
    manager = _make_manager(has_cartridges=True)
    manager.permanently_failed = True
    bridge = AlphaBridgeCartridge(manager=manager)
    event = _make_event()
    result = await bridge.process(event, MagicMock())
    assert result is event
    assert "_alpha_results" not in event.payload


@pytest.mark.asyncio
async def test_attaches_alpha_results_on_success():
    manager = _make_manager(has_cartridges=True)
    bridge = AlphaBridgeCartridge(manager=manager)
    event = _make_event()

    response_dict = {"envelope": None, "error": None, "duration_ms": 5.0}

    context = MagicMock()
    context.catalog.list_all.return_value = []

    with (
        patch("teleclaude_events.alpha.bridge.scan_cartridges", return_value=["echo_cart"]),
        patch("asyncio.open_unix_connection", new=AsyncMock()) as mock_conn,
        patch("teleclaude_events.alpha.bridge.write_frame", new=AsyncMock()),
        patch("teleclaude_events.alpha.bridge.read_frame", new=AsyncMock(return_value=response_dict)),
    ):
        mock_writer = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        mock_conn.return_value = (AsyncMock(), mock_writer)

        result = await bridge.process(event, context)

    assert result is event
    assert "_alpha_results" in result.payload
    assert len(result.payload["_alpha_results"]) == 1
    assert result.payload["_alpha_results"][0]["cartridge"] == "echo_cart"


@pytest.mark.asyncio
async def test_timeout_does_not_raise():
    manager = _make_manager(has_cartridges=True)
    bridge = AlphaBridgeCartridge(manager=manager)
    event = _make_event()

    context = MagicMock()
    context.catalog.list_all.return_value = []

    with (
        patch("teleclaude_events.alpha.bridge.scan_cartridges", return_value=["slow_cart"]),
        patch("asyncio.open_unix_connection", side_effect=asyncio.TimeoutError),
    ):
        result = await bridge.process(event, context)

    assert result is event
    assert "_alpha_results" in result.payload
    assert result.payload["_alpha_results"][0]["error"] == "timeout"


@pytest.mark.asyncio
async def test_connection_error_does_not_raise():
    manager = _make_manager(has_cartridges=True)
    bridge = AlphaBridgeCartridge(manager=manager)
    event = _make_event()

    context = MagicMock()
    context.catalog.list_all.return_value = []

    with (
        patch("teleclaude_events.alpha.bridge.scan_cartridges", return_value=["conn_cart"]),
        patch("asyncio.open_unix_connection", side_effect=ConnectionRefusedError("refused")),
    ):
        result = await bridge.process(event, context)

    assert result is event
    assert result.payload["_alpha_results"][0]["error"] == "unavailable"


@pytest.mark.asyncio
async def test_bridge_never_returns_none():
    manager = _make_manager(has_cartridges=False)
    bridge = AlphaBridgeCartridge(manager=manager)
    event = _make_event()
    result = await bridge.process(event, MagicMock())
    assert result is not None
