"""Tests for teleclaude.core.polling_coordinator helpers."""

from __future__ import annotations

import pytest

from teleclaude.core.events import AgentHookEvents
from teleclaude.core.polling_coordinator import (
    _codex_turn_state,
    _mark_codex_turn_started,
    _maybe_emit_codex_turn_events,
    _percentile,
)


class TestPercentile:
    @pytest.mark.unit
    def test_empty_values_returns_none(self):
        assert _percentile([], 0.5) is None

    @pytest.mark.unit
    def test_single_value_returns_it(self):
        assert _percentile([42.0], 0.5) == 42.0

    @pytest.mark.unit
    def test_median_of_sorted_list(self):
        result = _percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.5)
        assert result == 3.0

    @pytest.mark.unit
    def test_p95_approximation(self):
        values = list(range(1, 101))
        result = _percentile([float(v) for v in values], 0.95)
        assert result is not None
        assert result >= 90.0

    @pytest.mark.unit
    def test_p0_returns_minimum(self):
        result = _percentile([5.0, 3.0, 1.0, 4.0, 2.0], 0.0)
        assert result == 1.0


class TestCodexThinkingSuppression:
    @pytest.mark.asyncio
    async def test_suppresses_thinking_after_agent_stop_until_new_turn(self):
        session_id = "sess-thinking-stop"
        _codex_turn_state.pop(session_id, None)
        emitted: list[str] = []

        async def emit_agent_event(context):
            emitted.append(context.event_type)

        try:
            await _maybe_emit_codex_turn_events(
                session_id=session_id,
                active_agent="codex",
                current_output="• Working (7s • esc to interrupt)",
                session_last_agent_stop_at=None,
                emit_agent_event=emit_agent_event,
                enable_synthetic_turn_events=True,
            )
            assert AgentHookEvents.THINKING in emitted

            emitted.clear()
            await _maybe_emit_codex_turn_events(
                session_id=session_id,
                active_agent="codex",
                current_output="• Working (8s • esc to interrupt)",
                session_last_agent_stop_at="2026-03-31T18:40:00+00:00",
                emit_agent_event=emit_agent_event,
                enable_synthetic_turn_events=True,
            )
            assert emitted == []

            _mark_codex_turn_started(session_id)
            await _maybe_emit_codex_turn_events(
                session_id=session_id,
                active_agent="codex",
                current_output="• Working (9s • esc to interrupt)",
                session_last_agent_stop_at="2026-03-31T18:40:00+00:00",
                emit_agent_event=emit_agent_event,
                enable_synthetic_turn_events=True,
            )
            assert emitted == [AgentHookEvents.THINKING]
        finally:
            _codex_turn_state.pop(session_id, None)

    @pytest.mark.asyncio
    async def test_baselines_existing_stop_timestamp_without_suppressing_live_turn(self):
        session_id = "sess-thinking-baseline"
        _codex_turn_state.pop(session_id, None)
        emitted: list[str] = []

        async def emit_agent_event(context):
            emitted.append(context.event_type)

        try:
            await _maybe_emit_codex_turn_events(
                session_id=session_id,
                active_agent="codex",
                current_output="• Working (7s • esc to interrupt)",
                session_last_agent_stop_at="2026-03-31T18:39:00+00:00",
                emit_agent_event=emit_agent_event,
                enable_synthetic_turn_events=True,
            )
            assert emitted == [AgentHookEvents.THINKING]
        finally:
            _codex_turn_state.pop(session_id, None)
