"""Characterization tests for teleclaude.events.cartridges.trust."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.events.cartridges.trust import TrustCartridge, TrustConfig, TrustOutcome
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility


def _make_event(source: str = "known-source", level: EventLevel = EventLevel.OPERATIONAL) -> EventEnvelope:
    return EventEnvelope(
        event="test.event",
        source=source,
        level=level,
        domain="test",
        visibility=EventVisibility.LOCAL,
    )


def _make_context(config: TrustConfig) -> MagicMock:
    ctx = MagicMock()
    ctx.trust_config = config
    ctx.db = MagicMock()
    ctx.db.quarantine_event = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_permissive_always_accepts():
    """Permissive strictness accepts all events regardless of source."""
    config = TrustConfig(strictness="permissive", known_sources=frozenset())
    cartridge = TrustCartridge()
    event = _make_event(source="unknown-source")
    ctx = _make_context(config)

    result = await cartridge.process(event, ctx)

    assert result is event
    ctx.db.quarantine_event.assert_not_called()


@pytest.mark.asyncio
async def test_standard_unknown_source_flags_event():
    """Standard strictness flags events from unknown sources."""
    config = TrustConfig(strictness="standard", known_sources=frozenset({"trusted"}))
    cartridge = TrustCartridge()
    event = _make_event(source="unknown")
    ctx = _make_context(config)

    result = await cartridge.process(event, ctx)

    assert result is not None
    assert "_trust_flags" in result.payload
    assert "unknown_source" in result.payload["_trust_flags"]


@pytest.mark.asyncio
async def test_standard_known_source_accepts():
    """Standard strictness accepts events from known sources with valid level."""
    config = TrustConfig(strictness="standard", known_sources=frozenset({"known-source"}))
    cartridge = TrustCartridge()
    event = _make_event(source="known-source")
    ctx = _make_context(config)

    result = await cartridge.process(event, ctx)

    assert result is event
    assert "_trust_flags" not in result.payload


@pytest.mark.asyncio
async def test_strict_unknown_source_quarantines():
    """Strict mode quarantines events from unknown sources."""
    config = TrustConfig(strictness="strict", known_sources=frozenset({"trusted"}))
    cartridge = TrustCartridge()
    event = _make_event(source="unknown")
    ctx = _make_context(config)

    result = await cartridge.process(event, ctx)

    assert result is None
    ctx.db.quarantine_event.assert_called_once()


@pytest.mark.asyncio
async def test_strict_missing_domain_flags_non_system_event():
    """Strict mode flags events without domain unless event type starts with 'system.'."""
    config = TrustConfig(strictness="strict", known_sources=frozenset({"known-source"}))
    cartridge = TrustCartridge()
    event = EventEnvelope(
        event="custom.event",
        source="known-source",
        level=EventLevel.OPERATIONAL,
        domain="",
        visibility=EventVisibility.LOCAL,
    )
    ctx = _make_context(config)

    result = await cartridge.process(event, ctx)

    assert result is not None
    assert "_trust_flags" in result.payload
    assert "missing_domain" in result.payload["_trust_flags"]


@pytest.mark.asyncio
async def test_strict_system_event_without_domain_accepted():
    """Strict mode does not flag system.* events even when domain is empty."""
    config = TrustConfig(strictness="strict", known_sources=frozenset({"known-source"}))
    cartridge = TrustCartridge()
    event = EventEnvelope(
        event="system.worker.crashed",
        source="known-source",
        level=EventLevel.OPERATIONAL,
        domain="",
        visibility=EventVisibility.LOCAL,
    )
    ctx = _make_context(config)

    result = await cartridge.process(event, ctx)

    assert result is event


@pytest.mark.asyncio
async def test_evaluate_returns_outcome_and_flags():
    """_evaluate returns (outcome, flags) tuple consistently."""
    config = TrustConfig(strictness="standard", known_sources=frozenset())
    cartridge = TrustCartridge()
    event = _make_event(source="unknown")

    outcome, flags = cartridge._evaluate(event, config)

    assert outcome == TrustOutcome.FLAG
    assert isinstance(flags, list)
    assert "unknown_source" in flags


@pytest.mark.asyncio
async def test_quarantine_event_called_with_correct_args():
    """Quarantine path calls db.quarantine_event with event and flags."""
    config = TrustConfig(strictness="strict", known_sources=frozenset())
    cartridge = TrustCartridge()
    event = _make_event(source="unknown")
    ctx = _make_context(config)

    await cartridge.process(event, ctx)

    call_args = ctx.db.quarantine_event.call_args
    assert call_args[0][0] is event
    assert "unknown_source" in call_args[0][1]
