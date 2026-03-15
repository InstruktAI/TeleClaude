"""Characterization tests for teleclaude.hooks.utils.parse_helpers."""

from __future__ import annotations

import pytest

from teleclaude.hooks.utils.parse_helpers import coerce_str, get_str


class TestCoerceStr:
    @pytest.mark.unit
    def test_returns_trimmed_non_empty_strings(self) -> None:
        assert coerce_str("  hello  ") == "hello"

    @pytest.mark.unit
    def test_returns_none_for_empty_or_non_string_values(self) -> None:
        assert coerce_str("   ") is None
        assert coerce_str(3) is None


class TestGetStr:
    @pytest.mark.unit
    def test_reads_and_trims_a_top_level_string_value(self) -> None:
        assert get_str({"name": "  teleclaude  "}, "name") == "teleclaude"

    @pytest.mark.unit
    def test_returns_none_for_missing_or_non_string_top_level_values(self) -> None:
        assert get_str({"count": 1}, "count") is None
        assert get_str({}, "missing") is None
