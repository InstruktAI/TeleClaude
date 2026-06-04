"""Tests for teleclaude.events.cartridges.lifecycle_router."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.events.cartridges.lifecycle_router import LifecycleRouterCartridge
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility

_WORKFLOW_TODO_CREATED = "workflow.todo.created"
_KIND_FEATURE = "feature"


def _make_event(
    event_type: str = "domain.software-development.planning.artifact_changed",
    slug: str = "my-slug",
) -> EventEnvelope:
    return EventEnvelope(
        event=event_type,
        source="test",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        visibility=EventVisibility.LOCAL,
        payload={"slug": slug},
    )


def _make_workflow_todo_created(
    slug: str = "my-slug",
    kind: str = "feature",
    pickup_requested: bool = True,
    originating_computer: str | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        event=_WORKFLOW_TODO_CREATED,
        source="test",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        visibility=EventVisibility.LOCAL,
        originating_computer=originating_computer,
        payload={"slug": slug, "kind": kind, "pickup_requested": pickup_requested},
    )


@pytest.mark.asyncio
async def test_non_planning_event_passes_through() -> None:
    cartridge = LifecycleRouterCartridge()
    event = _make_event("system.worker.started")
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event


@pytest.mark.asyncio
async def test_planning_event_not_in_trigger_set_passes_through() -> None:
    cartridge = LifecycleRouterCartridge()
    event = _make_event("domain.software-development.planning.other_event")
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event


@pytest.mark.asyncio
async def test_event_without_slug_passes_through() -> None:
    cartridge = LifecycleRouterCartridge()
    event = EventEnvelope(
        event="domain.software-development.planning.artifact_changed",
        source="test",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        visibility=EventVisibility.LOCAL,
        payload={},
    )
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event


@pytest.mark.asyncio
async def test_non_dump_planning_trigger_passes_without_notification_work() -> None:
    cartridge = LifecycleRouterCartridge()
    event = _make_event("domain.software-development.planning.artifact_changed")
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event
    ctx.db.find_by_group_key.assert_not_called()
    ctx.db.update_agent_status.assert_not_called()
    ctx.db.resolve_notification.assert_not_called()


# ---------------------------------------------------------------------------
# Specs (xfail) for guaranteed-event-consumption
# These pin the post-implementation contract; remove pytestmark when satisfied.
# ---------------------------------------------------------------------------


class TestLifecycleRouterDispatchPropagationSpecs:
    """Lane-dispatch failures must surface as delivery failures, not be swallowed.

    Verbatim requirement criterion (from `requirements.md`):

    > **No silent success at named sites.** Spawn failures in
    > `IntegrationTriggerCartridge._spawn_integrator`, lane-dispatch failures
    > in `LifecycleRouterCartridge._dispatch_router_lane`, and handler
    > exceptions in `DomainPipeline._run_handler` propagate as delivery
    > failures rather than being swallowed and treated as success. Deliberate
    > skips (e.g. `AutonomyLevel.MANUAL`) remain non-failures.
    """

    @pytest.mark.asyncio
    async def test_lane_dispatch_failure_propagates_from_process(self) -> None:
        """When the dispatch path raises, ``process`` must raise rather than return success."""
        cartridge = LifecycleRouterCartridge()
        event = _make_workflow_todo_created(kind="todo")
        ctx = MagicMock()

        failing_client = MagicMock()
        failing_client.connect = AsyncMock()
        failing_client.run_session = AsyncMock(side_effect=RuntimeError("dispatch failure"))
        failing_client.close = AsyncMock()

        with (
            patch(
                "teleclaude.events.cartridges.lifecycle_router.TelecAPIClient",
                return_value=failing_client,
            ),
            pytest.raises(RuntimeError, match="dispatch failure"),
        ):
            await cartridge.process(event, ctx)


@pytest.mark.asyncio
async def test_workflow_todo_created_passes_prefix_gate() -> None:
    cartridge = LifecycleRouterCartridge()
    event = _make_workflow_todo_created()
    ctx = MagicMock()

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.run_session = AsyncMock()
    mock_client.close = AsyncMock()

    with patch(
        "teleclaude.events.cartridges.lifecycle_router.TelecAPIClient",
        return_value=mock_client,
    ):
        result = await cartridge.process(event, ctx)

    assert result is event


@pytest.mark.asyncio
async def test_workflow_todo_created_with_pickup_requested_true_triggers_dispatch() -> None:
    cartridge = LifecycleRouterCartridge()
    event = _make_workflow_todo_created(pickup_requested=True)
    ctx = MagicMock()

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.run_session = AsyncMock()
    mock_client.close = AsyncMock()

    with patch(
        "teleclaude.events.cartridges.lifecycle_router.TelecAPIClient",
        return_value=mock_client,
    ):
        await cartridge.process(event, ctx)

    mock_client.run_session.assert_called_once()


@pytest.mark.asyncio
async def test_workflow_todo_created_with_local_origin_triggers_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("teleclaude.events.cartridges.lifecycle_router.config.computer.name", "MozMini")
    cartridge = LifecycleRouterCartridge()
    event = _make_workflow_todo_created(originating_computer="MozMini")
    ctx = MagicMock()

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.run_session = AsyncMock()
    mock_client.close = AsyncMock()

    with patch(
        "teleclaude.events.cartridges.lifecycle_router.TelecAPIClient",
        return_value=mock_client,
    ):
        result = await cartridge.process(event, ctx)

    assert result is event
    mock_client.run_session.assert_called_once()


@pytest.mark.asyncio
async def test_workflow_todo_created_with_foreign_origin_skips_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("teleclaude.events.cartridges.lifecycle_router.config.computer.name", "MozMini")
    cartridge = LifecycleRouterCartridge()
    event = _make_workflow_todo_created(originating_computer="MozBook")
    ctx = MagicMock()

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.run_session = AsyncMock()
    mock_client.close = AsyncMock()

    with patch(
        "teleclaude.events.cartridges.lifecycle_router.TelecAPIClient",
        return_value=mock_client,
    ):
        result = await cartridge.process(event, ctx)

    assert result is event
    mock_client.run_session.assert_not_called()


@pytest.mark.asyncio
async def test_workflow_todo_created_without_origin_keeps_legacy_dispatch() -> None:
    cartridge = LifecycleRouterCartridge()
    event = _make_workflow_todo_created(originating_computer=None)
    ctx = MagicMock()

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.run_session = AsyncMock()
    mock_client.close = AsyncMock()

    with patch(
        "teleclaude.events.cartridges.lifecycle_router.TelecAPIClient",
        return_value=mock_client,
    ):
        result = await cartridge.process(event, ctx)

    assert result is event
    mock_client.run_session.assert_called_once()


@pytest.mark.asyncio
async def test_workflow_todo_created_with_pickup_requested_false_skips_dispatch() -> None:
    cartridge = LifecycleRouterCartridge()
    event = _make_workflow_todo_created(pickup_requested=False)
    ctx = MagicMock()

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.run_session = AsyncMock()
    mock_client.close = AsyncMock()

    with patch(
        "teleclaude.events.cartridges.lifecycle_router.TelecAPIClient",
        return_value=mock_client,
    ):
        await cartridge.process(event, ctx)

    mock_client.run_session.assert_not_called()


@pytest.mark.asyncio
async def test_workflow_todo_created_absent_pickup_requested_defaults_true() -> None:
    """No pickup_requested key in payload → defaults True → dispatch fires."""
    cartridge = LifecycleRouterCartridge()
    event = EventEnvelope(
        event=_WORKFLOW_TODO_CREATED,
        source="test",
        level=EventLevel.WORKFLOW,
        domain="software-development",
        visibility=EventVisibility.LOCAL,
        payload={"slug": "my-slug", "kind": _KIND_FEATURE},
    )
    ctx = MagicMock()

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.run_session = AsyncMock()
    mock_client.close = AsyncMock()

    with patch(
        "teleclaude.events.cartridges.lifecycle_router.TelecAPIClient",
        return_value=mock_client,
    ):
        await cartridge.process(event, ctx)

    mock_client.run_session.assert_called_once()


@pytest.mark.asyncio
async def test_unknown_kind_still_dispatches() -> None:
    cartridge = LifecycleRouterCartridge()
    event = _make_workflow_todo_created(kind="unknown-lane")
    ctx = MagicMock()

    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.run_session = AsyncMock()
    mock_client.close = AsyncMock()

    with patch(
        "teleclaude.events.cartridges.lifecycle_router.TelecAPIClient",
        return_value=mock_client,
    ):
        await cartridge.process(event, ctx)

    mock_client.run_session.assert_called_once()
