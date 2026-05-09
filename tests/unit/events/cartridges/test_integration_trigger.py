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
async def test_no_spawn_callback_passes_through():
    """Without a spawn callback, todo_finalize_ready passes through silently."""
    cartridge = IntegrationTriggerCartridge()
    event = _make_event(_SPAWN_EVENT, _FINALIZE_READY_PAYLOAD)
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event


# ---------------------------------------------------------------------------
# Specs (xfail) for guaranteed-event-consumption
# These pin the post-implementation contract; remove pytestmark when satisfied.
# ---------------------------------------------------------------------------


class TestIntegrationTriggerSpawnPropagationSpecs:
    """Spawn-callback exceptions must surface as delivery failures, not be swallowed.

    Verbatim requirement criterion (from `requirements.md`):

    > **No silent success at named sites.** Spawn failures in
    > `IntegrationTriggerCartridge._spawn_integrator`, lane-dispatch failures
    > in `LifecycleRouterCartridge._dispatch_router_lane`, and handler
    > exceptions in `DomainPipeline._run_handler` propagate as delivery
    > failures rather than being swallowed and treated as success. Deliberate
    > skips (e.g. `AutonomyLevel.MANUAL`) remain non-failures.
    """

    @pytest.mark.asyncio
    async def test_spawn_callback_exception_propagates_from_process(self) -> None:
        """When the spawn callback raises, ``process`` must raise rather than return the event."""
        spawn = AsyncMock(side_effect=RuntimeError("spawn failure"))
        cartridge = IntegrationTriggerCartridge(spawn_callback=spawn)
        event = _make_event(_SPAWN_EVENT, _FINALIZE_READY_PAYLOAD)
        ctx = MagicMock()

        with pytest.raises(RuntimeError, match="spawn failure"):
            await cartridge.process(event, ctx)


class TestIntegrationTriggerIdempotentRedeliverySpecs:
    """Redelivery of the same logical finalize-ready event must not spawn the integrator twice.

    Verbatim requirement criterion (from `requirements.md`):

    > **Idempotent-redelivery contract.** Redelivery of an event that
    > previously partially succeeded does not produce duplicate
    > externally-visible work. `IntegrationTriggerCartridge` does not spawn
    > or wake the integrator more than once for the same logical event when
    > that event is redelivered. The cartridge interface contract requires
    > every required cartridge to tolerate redelivery; this requirement is
    > satisfied by behavior, not by any specific reordering or guarding
    > mechanism.
    """

    @pytest.mark.asyncio
    async def test_redelivery_of_same_event_invokes_spawn_callback_at_most_once(self) -> None:
        """Two ``process`` calls with the same logical event yield at most one spawn-callback invocation."""
        spawn = AsyncMock()
        cartridge = IntegrationTriggerCartridge(spawn_callback=spawn)
        event = _make_event(_SPAWN_EVENT, _FINALIZE_READY_PAYLOAD)
        ctx = MagicMock()

        await cartridge.process(event, ctx)
        await cartridge.process(event, ctx)

        assert spawn.call_count == 1
