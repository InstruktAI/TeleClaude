"""Characterization tests for event emission routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.api import event_routes
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility


class TestEventRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_emit_event_endpoint_forwards_envelope_fields(self) -> None:
        """The emit route forwards the envelope contract unchanged to the producer."""
        body = EventEnvelope(
            event="todo.created",
            source="tests",
            level=EventLevel.WORKFLOW,
            domain="todos",
            description="created",
            payload={"slug": "chartest-api-routes"},
            visibility=EventVisibility.PUBLIC,
            entity="todo:chartest-api-routes",
        )

        with patch("teleclaude.api.event_routes.emit_event", new=AsyncMock(return_value="entry-123")) as emit_event:
            response = await event_routes.emit_event_endpoint(body, _identity=object())

        assert response.entry_id == "entry-123"
        emit_event.assert_awaited_once_with(
            event="todo.created",
            source="tests",
            level=EventLevel.WORKFLOW,
            domain="todos",
            description="created",
            payload={"slug": "chartest-api-routes"},
            visibility=EventVisibility.PUBLIC,
            entity="todo:chartest-api-routes",
        )
