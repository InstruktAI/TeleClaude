"""Tests for teleclaude.events.cartridges.integration_trigger."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.core.integration.events import (
    BranchPushedPayload,
    CandidateDeliveredPayload,
    FinalizeReadyPayload,
    ReviewApprovedPayload,
)
from teleclaude.events.cartridges.integration_trigger import (
    INTEGRATION_EVENT_TYPES,
    IntegrationTriggerCartridge,
)
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility


def _make_event(
    event_type: str,
    payload: FinalizeReadyPayload | ReviewApprovedPayload | BranchPushedPayload | CandidateDeliveredPayload,
) -> EventEnvelope:
    return EventEnvelope(
        event=event_type,
        source="test",
        level=EventLevel.OPERATIONAL,
        domain="test",
        visibility=EventVisibility.LOCAL,
        payload=payload,
    )


_FINALIZE_READY: FinalizeReadyPayload = {
    "slug": "my-slug",
    "branch": "my-slug",
    "sha": "deadbeef1234",
    "worker_session_id": "w-001",
    "orchestrator_session_id": "o-001",
    "ready_at": "2025-03-25T00:00:00Z",
}

_REVIEW_APPROVED: ReviewApprovedPayload = {
    "slug": "my-slug",
    "approved_at": "2025-03-25T00:00:00Z",
    "review_round": 1,
    "reviewer_session_id": "r-001",
}

_BRANCH_PUSHED: BranchPushedPayload = {
    "branch": "my-slug",
    "sha": "deadbeef1234",
    "remote": "origin",
    "pushed_at": "2025-03-25T00:00:00Z",
    "pusher": "worker",
}

_CANDIDATE_DELIVERED: CandidateDeliveredPayload = {
    "slug": "my-slug",
    "branch": "my-slug",
    "merge_commit_sha": "abc123",
}


@pytest.mark.asyncio
async def test_non_integration_event_passes_through():
    """Events not in INTEGRATION_EVENT_TYPES pass through unchanged."""
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
async def test_deployment_started_triggers_spawn():
    """deployment.started immediately spawns the integrator."""
    spawn = AsyncMock()
    cartridge = IntegrationTriggerCartridge(spawn_callback=spawn)
    event = _make_event("domain.software-development.deployment.started", _FINALIZE_READY)
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event
    spawn.assert_called_once_with("my-slug", "my-slug", "deadbeef1234")


@pytest.mark.asyncio
async def test_review_approved_does_not_spawn():
    """review.approved passes through without spawning."""
    spawn = AsyncMock()
    cartridge = IntegrationTriggerCartridge(spawn_callback=spawn)
    event = _make_event("domain.software-development.review.approved", _REVIEW_APPROVED)
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_branch_pushed_does_not_spawn():
    """branch.pushed passes through without spawning."""
    spawn = AsyncMock()
    cartridge = IntegrationTriggerCartridge(spawn_callback=spawn)
    event = _make_event("domain.software-development.branch.pushed", _BRANCH_PUSHED)
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_deployment_completed_does_not_spawn():
    """deployment.completed passes through without spawning."""
    spawn = AsyncMock()
    cartridge = IntegrationTriggerCartridge(spawn_callback=spawn)
    event = _make_event("domain.software-development.deployment.completed", _CANDIDATE_DELIVERED)
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_spawn_exception_does_not_propagate():
    """Spawn callback failure is swallowed — event still returned."""
    spawn = AsyncMock(side_effect=RuntimeError("spawn failure"))
    cartridge = IntegrationTriggerCartridge(spawn_callback=spawn)
    event = _make_event("domain.software-development.deployment.started", _FINALIZE_READY)
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event


@pytest.mark.asyncio
async def test_no_spawn_callback_passes_through():
    """Without a spawn callback, deployment.started passes through silently."""
    cartridge = IntegrationTriggerCartridge()
    event = _make_event("domain.software-development.deployment.started", _FINALIZE_READY)
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event


def test_integration_event_types_contains_expected():
    """INTEGRATION_EVENT_TYPES contains the lifecycle events."""
    assert "domain.software-development.deployment.started" in INTEGRATION_EVENT_TYPES
    assert "domain.software-development.deployment.completed" in INTEGRATION_EVENT_TYPES
    assert "domain.software-development.deployment.failed" in INTEGRATION_EVENT_TYPES
    assert "domain.software-development.review.approved" in INTEGRATION_EVENT_TYPES
    assert "domain.software-development.branch.pushed" in INTEGRATION_EVENT_TYPES
