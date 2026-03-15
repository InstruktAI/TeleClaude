"""Characterization tests for teleclaude.events.cartridges.integration_trigger."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.core.models import JsonDict
from teleclaude.events.cartridges.integration_trigger import (
    INTEGRATION_EVENT_TYPES,
    IntegrationTriggerCartridge,
    _strip_pipeline_metadata,
)
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility


def _make_event(
    event_type: str = "test.event",
    payload: dict[str, object] | None = None,  # guard: loose-dict
) -> EventEnvelope:
    return EventEnvelope(
        event=event_type,
        source="test",
        level=EventLevel.OPERATIONAL,
        domain="test",
        visibility=EventVisibility.LOCAL,
        payload=payload or {},
    )


@pytest.mark.asyncio
async def test_non_integration_event_passes_through():
    """Events not in INTEGRATION_EVENT_TYPES pass through unchanged."""
    cartridge = IntegrationTriggerCartridge()
    event = _make_event("test.unrelated")
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event


@pytest.mark.asyncio
async def test_review_approved_calls_ingest_with_canonical_type():
    """review.approved event is translated to 'review_approved' canonical type."""
    ready_candidates: list[tuple[str, str, str]] = []
    ingest = MagicMock(return_value=ready_candidates)
    cartridge = IntegrationTriggerCartridge(ingest_callback=ingest)
    event = _make_event(
        "domain.software-development.review.approved",
        payload={"slug": "my-todo", "branch": "feat/x", "sha": "abc123"},
    )
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event
    ingest.assert_called_once()
    canonical_type = ingest.call_args[0][0]
    assert canonical_type == "review_approved"


@pytest.mark.asyncio
async def test_branch_pushed_calls_ingest():
    """branch.pushed event is translated to 'branch_pushed' canonical type."""
    ingest = MagicMock(return_value=[])
    cartridge = IntegrationTriggerCartridge(ingest_callback=ingest)
    event = _make_event(
        "domain.software-development.branch.pushed",
        payload={"slug": "s", "branch": "b", "sha": "s"},
    )
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event
    assert ingest.call_args[0][0] == "branch_pushed"


@pytest.mark.asyncio
async def test_ready_candidate_triggers_spawn_callback():
    """When ingest returns a ready candidate, spawn callback is invoked."""
    spawn = AsyncMock()
    ingest = MagicMock(return_value=[("my-slug", "main", "deadbeef")])
    cartridge = IntegrationTriggerCartridge(spawn_callback=spawn, ingest_callback=ingest)
    event = _make_event(
        "domain.software-development.review.approved",
        payload={"slug": "my-slug", "branch": "main", "sha": "deadbeef"},
    )
    ctx = MagicMock()

    await cartridge.process(event, ctx)

    spawn.assert_called_once_with("my-slug", "main", "deadbeef")


@pytest.mark.asyncio
async def test_no_ready_candidates_skips_spawn():
    """When ingest returns no candidates, spawn callback is not called."""
    spawn = AsyncMock()
    ingest = MagicMock(return_value=[])
    cartridge = IntegrationTriggerCartridge(spawn_callback=spawn, ingest_callback=ingest)
    event = _make_event(
        "domain.software-development.review.approved",
        payload={"slug": "s", "branch": "b", "sha": "c"},
    )
    ctx = MagicMock()

    await cartridge.process(event, ctx)

    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_exception_does_not_propagate():
    """Ingest callback failure is swallowed — event still returned."""
    ingest = MagicMock(side_effect=RuntimeError("boom"))
    cartridge = IntegrationTriggerCartridge(ingest_callback=ingest)
    event = _make_event(
        "domain.software-development.review.approved",
        payload={"slug": "s", "branch": "b", "sha": "c"},
    )
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event


@pytest.mark.asyncio
async def test_spawn_exception_does_not_propagate():
    """Spawn callback failure is swallowed — event still returned."""
    spawn = AsyncMock(side_effect=RuntimeError("spawn failure"))
    ingest = MagicMock(return_value=[("s", "b", "c")])
    cartridge = IntegrationTriggerCartridge(spawn_callback=spawn, ingest_callback=ingest)
    event = _make_event(
        "domain.software-development.review.approved",
        payload={"slug": "s", "branch": "b", "sha": "c"},
    )
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event


def test_strip_pipeline_metadata_removes_underscore_keys():
    """_strip_pipeline_metadata removes keys starting with underscore."""
    payload = {"slug": "x", "_trust_flags": ["flag"], "_classification": {}, "sha": "abc"}
    cleaned = _strip_pipeline_metadata(payload)
    assert "slug" in cleaned
    assert "sha" in cleaned
    assert "_trust_flags" not in cleaned
    assert "_classification" not in cleaned


def test_integration_event_types_set_is_non_empty():
    """INTEGRATION_EVENT_TYPES contains the expected canonical events."""
    assert "domain.software-development.review.approved" in INTEGRATION_EVENT_TYPES
    assert "domain.software-development.branch.pushed" in INTEGRATION_EVENT_TYPES


@pytest.mark.asyncio
async def test_deployment_completed_passes_through_without_ingest():
    """deployment.completed is in INTEGRATION_EVENT_TYPES but has no canonical mapping — passes through."""
    ingest = MagicMock(return_value=[])
    cartridge = IntegrationTriggerCartridge(ingest_callback=ingest)
    event = _make_event(
        "domain.software-development.deployment.completed",
        payload={"slug": "s", "branch": "b", "sha": "c"},
    )
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event
    ingest.assert_not_called()


@pytest.mark.asyncio
async def test_deployment_started_calls_ingest_with_finalize_ready():
    """deployment.started maps to 'finalize_ready' canonical type via process()."""
    ingest = MagicMock(return_value=[])
    cartridge = IntegrationTriggerCartridge(ingest_callback=ingest)
    event = _make_event(
        "domain.software-development.deployment.started",
        payload={"slug": "s", "branch": "b", "sha": "c"},
    )
    ctx = MagicMock()

    result = await cartridge.process(event, ctx)

    assert result is event
    ingest.assert_called_once()
    assert ingest.call_args[0][0] == "finalize_ready"


@pytest.mark.asyncio
async def test_process_passes_sanitized_payload_to_ingest():
    """process() strips underscore-prefixed pipeline metadata before forwarding to ingest."""
    received: list[JsonDict] = []

    def capture_ingest(canonical_type: str, payload: JsonDict) -> list[tuple[str, str, str]]:
        received.append(dict(payload))
        return []

    cartridge = IntegrationTriggerCartridge(ingest_callback=capture_ingest)
    event = _make_event(
        "domain.software-development.review.approved",
        payload={
            "slug": "x",
            "branch": "main",
            "sha": "abc",
            "_trust_flags": ["trusted"],
            "_classification": {"label": "ok"},
        },
    )
    ctx = MagicMock()

    await cartridge.process(event, ctx)

    assert len(received) == 1
    payload = received[0]
    assert "slug" in payload
    assert "_trust_flags" not in payload
    assert "_classification" not in payload
