"""Tests for teleclaude.core.polling_coordinator._percentile."""

from __future__ import annotations

import pytest

from teleclaude.core.polling_coordinator import _percentile


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
