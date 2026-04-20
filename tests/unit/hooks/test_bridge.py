"""Characterization tests for teleclaude.hooks.bridge."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from teleclaude.core.events import ToolUseActivityEvent
from teleclaude.hooks.bridge import EventBusBridge
from teleclaude.hooks.webhook_models import HookEvent


@dataclass
class _DispatcherStub:
    events: list[HookEvent] = field(default_factory=list)

    async def dispatch(self, event: HookEvent) -> None:
        self.events.append(event)


class TestEventBusBridge:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_dispatches_tool_use_activity_with_tool_name_property(self) -> None:
        dispatcher = _DispatcherStub()
        bridge = EventBusBridge(dispatcher)
        context = ToolUseActivityEvent(
            session_id="sess-2",
            event_type="tool_use",
            timestamp="2026-01-01T00:00:00Z",
            tool_name="shell",
            tool_preview="shell ls",
        )

        await bridge._handle("agent_activity", context)

        assert dispatcher.events[0].type == "agent.activity.tool_use"
        assert dispatcher.events[0].properties["tool_name"] == "shell"
