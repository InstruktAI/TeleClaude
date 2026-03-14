"""Characterization tests for teleclaude.core.event_guard."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from teleclaude.core.event_guard import create_event_guard
from teleclaude.core.events import TeleClaudeEvents


def _make_emit():
    return MagicMock()


class TestCreateEventGuard:
    @pytest.mark.unit
    async def test_successful_handler_called_and_returns(self):
        result_holder = []

        async def handler(event_name, context):
            result_holder.append("called")
            return "ok"

        emit = _make_emit()
        guarded = create_event_guard(handler, emit=emit)
        await guarded("agent_event", MagicMock())
        assert "called" in result_holder

    @pytest.mark.unit
    async def test_exception_emits_error_event(self):
        async def failing_handler(event_name, context):
            raise ValueError("test error")

        emitted_events = []

        def emit(event_type, ctx):
            emitted_events.append((event_type, ctx))

        guarded = create_event_guard(failing_handler, emit=emit)
        result = await guarded("agent_event", MagicMock(session_id="sess-001"))
        assert result is None
        assert len(emitted_events) == 1
        assert emitted_events[0][0] == TeleClaudeEvents.ERROR

    @pytest.mark.unit
    async def test_error_event_does_not_re_emit(self):
        async def error_handler(event_name, context):
            raise ValueError("in error handler")

        emitted = []

        def emit(event_type, ctx):
            emitted.append(event_type)

        guarded = create_event_guard(error_handler, emit=emit)
        # Calling with an error event type should NOT re-emit
        result = await guarded(TeleClaudeEvents.ERROR, MagicMock(session_id=None))
        assert result is None
        assert len(emitted) == 0

    @pytest.mark.unit
    async def test_returns_none_on_exception(self):
        async def bad_handler(event_name, context):
            raise RuntimeError("oops")

        guarded = create_event_guard(bad_handler, emit=_make_emit())
        result = await guarded("agent_event", MagicMock())
        assert result is None

    @pytest.mark.unit
    async def test_custom_handler_name_used(self):
        async def handler(event_name, context):
            pass

        guarded = create_event_guard(handler, emit=_make_emit(), handler_name="custom.name")
        result = await guarded("agent_event", MagicMock())
        # Handler returns None (pass); custom name does not alter return value
        assert result is None
