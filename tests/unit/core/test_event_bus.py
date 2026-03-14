"""Characterization tests for teleclaude.core.event_bus."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from teleclaude.core.event_bus import EventBus


class TestEventBus:
    @pytest.mark.unit
    async def test_subscribe_and_emit_fires_handler(self):
        bus = EventBus()
        calls: list[str] = []

        async def handler(event, context):
            calls.append(event)

        bus.subscribe("agent_event", handler)
        bus.emit("agent_event", MagicMock())
        await asyncio.sleep(0)
        assert "agent_event" in calls

    @pytest.mark.unit
    def test_emit_without_handler_does_not_raise(self):
        bus = EventBus()
        bus.emit("agent_event", MagicMock())
        # No handler registered; bus state is unchanged (no side effects)
        assert bus._handlers.get("agent_event") is None

    @pytest.mark.unit
    def test_clear_removes_all_handlers(self):
        bus = EventBus()
        calls: list[str] = []

        async def handler(event, context):
            calls.append(event)

        bus.subscribe("agent_event", handler)
        bus.clear()

        bus.emit("agent_event", MagicMock())
        assert len(calls) == 0

    @pytest.mark.unit
    async def test_multiple_handlers_for_same_event(self):
        bus = EventBus()
        results: list[str] = []

        async def h1(event, context):
            results.append("h1")

        async def h2(event, context):
            results.append("h2")

        bus.subscribe("agent_event", h1)
        bus.subscribe("agent_event", h2)
        bus.emit("agent_event", MagicMock())
        await asyncio.sleep(0.01)
        assert "h1" in results
        assert "h2" in results
