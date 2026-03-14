"""Characterization tests for teleclaude.core.session_utils."""

from __future__ import annotations

import pytest

from teleclaude.core.session_utils import unique_title


class TestUniqueTitle:
    @pytest.mark.unit
    def test_unique_title_returned_unchanged(self):
        result = unique_title("My Session", {"Other Session"})
        assert result == "My Session"

    @pytest.mark.unit
    def test_duplicate_title_gets_counter(self):
        result = unique_title("My Session", {"My Session"})
        assert result == "My Session (2)"

    @pytest.mark.unit
    def test_multiple_duplicates_increments_counter(self):
        existing = {"My Session", "My Session (2)", "My Session (3)"}
        result = unique_title("My Session", existing)
        assert result == "My Session (4)"

    @pytest.mark.unit
    def test_empty_existing_returns_base(self):
        result = unique_title("New Session", set())
        assert result == "New Session"

    @pytest.mark.unit
    def test_different_base_title_not_affected(self):
        result = unique_title("Session A", {"Session B", "Session C"})
        assert result == "Session A"
