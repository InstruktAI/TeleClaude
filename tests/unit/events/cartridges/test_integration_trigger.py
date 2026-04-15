"""Tests for teleclaude.events.cartridges.integration_trigger."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.events.cartridges.integration_trigger import (
    IntegrationTriggerCartridge,
)
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility

_SPAWN_EVENT = "domain.software-development.planning.todo_finalize_ready"


def _make_event(event_type: str, payload: dict) -> EventEnvelope:
    return EventEnvelope(
        event=event_type,
        source="test",
        level=EventLevel.OPERATIONAL,
        domain="test",
        visibility=EventVisibility.LOCAL,
        payload=payload,
    )


_FINALIZE_READY_PAYLOAD = {
    "slug": "my-slug",
    "branch": "my-slug",
    "sha": "deadbeef1234",
    "worker_session_id": "w-001",
}


@pytest.mark.asyncio
async def test_non_finalize_event_passes_through():
    """Events that are not todo_finalize_ready pass through unchanged."""
    cartridge = IntegrationTriggerCartridge()
    event = EventEnvelope(
        event="test.unrelated",
        source="test",
        level=EventLevel.OPERATIONAL,
        domain="test",
        visibility=EventVisibility.LOCAL,
    )
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event


@pytest.mark.asyncio
async def test_finalize_ready_triggers_spawn():
    """todo_finalize_ready immediately spawns the integrator."""
    spawn = AsyncMock()
    cartridge = IntegrationTriggerCartridge(spawn_callback=spawn)
    event = _make_event(_SPAWN_EVENT, _FINALIZE_READY_PAYLOAD)
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event
    spawn.assert_called_once_with("my-slug", "my-slug", "deadbeef1234", "w-001")


@pytest.mark.asyncio
async def test_spawn_exception_does_not_propagate():
    """Spawn callback failure is swallowed — event still returned."""
    spawn = AsyncMock(side_effect=RuntimeError("spawn failure"))
    cartridge = IntegrationTriggerCartridge(spawn_callback=spawn)
    event = _make_event(_SPAWN_EVENT, _FINALIZE_READY_PAYLOAD)
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event


@pytest.mark.asyncio
async def test_no_spawn_callback_passes_through():
    """Without a spawn callback, todo_finalize_ready passes through silently."""
    cartridge = IntegrationTriggerCartridge()
    event = _make_event(_SPAWN_EVENT, _FINALIZE_READY_PAYLOAD)
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event
