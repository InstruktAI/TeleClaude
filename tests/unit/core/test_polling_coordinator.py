"""Characterization tests for teleclaude.core.polling_coordinator."""

from __future__ import annotations

import pytest

from teleclaude.core.polling_coordinator import (
    CodexTurnState,
    OutputMetricsState,
    _percentile,
)


class TestCodexTurnState:
    @pytest.mark.unit
    def test_default_state_values(self):
        state = CodexTurnState()
        assert state.turn_active is False
        assert state.in_tool is False
        assert state.prompt_visible_last is False
        assert state.initialized is False
        assert state.last_tool_signature == ""

    @pytest.mark.unit
    def test_state_can_be_mutated(self):
        state = CodexTurnState()
        state.turn_active = True
        assert state.turn_active is True


class TestOutputMetricsState:
    @pytest.mark.unit
    def test_default_state_values(self):
        state = OutputMetricsState()
        assert state.ticks == 0
        assert state.fanout_chars == 0
        assert state.last_tick_at is None
        assert state.cadence_samples_s == []


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
