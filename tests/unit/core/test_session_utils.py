"""Characterization tests for teleclaude.core.session_utils."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from teleclaude.core.session_utils import session_display_title, unique_title


class TestSessionDisplayTitle:
    @pytest.mark.unit
    def test_returns_title_when_not_headless(self):
        session = SimpleNamespace(title="My session", lifecycle_status="active")
        assert session_display_title(session) == "My session"

    @pytest.mark.unit
    def test_prepends_marker_when_lifecycle_status_is_headless(self):
        session = SimpleNamespace(title="My session", lifecycle_status="headless")
        assert session_display_title(session) == "[HEADLESS] My session"

    @pytest.mark.unit
    def test_reads_status_when_lifecycle_status_attribute_is_absent(self):
        """DTO/snapshot path: the wire field is named ``status`` (lifecycle on the wire)."""
        session = SimpleNamespace(title="My session", status="headless")
        assert session_display_title(session) == "[HEADLESS] My session"

    @pytest.mark.unit
    def test_falls_back_to_default_when_title_is_empty(self):
        session = SimpleNamespace(title="", lifecycle_status="active")
        assert session_display_title(session) == "Untitled"

    @pytest.mark.unit
    def test_custom_fallback_is_honored(self):
        session = SimpleNamespace(title=None, lifecycle_status="active")
        assert session_display_title(session, fallback="(untitled)") == "(untitled)"

    @pytest.mark.unit
    def test_headless_marker_applies_to_fallback_too(self):
        session = SimpleNamespace(title="", lifecycle_status="headless")
        assert session_display_title(session) == "[HEADLESS] Untitled"


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
