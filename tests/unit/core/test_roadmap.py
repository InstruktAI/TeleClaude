"""Characterization tests for teleclaude.core.roadmap."""

from __future__ import annotations

import pytest

from teleclaude.core.models import TodoInfo

# _slugify_heading: pure slug normalization logic; tested directly since it has
# no public wrapper and is the canonical slug contract used throughout the module.
from teleclaude.core.roadmap import _slugify_heading, assemble_roadmap


class TestAssembleRoadmap:
    @pytest.mark.unit
    def test_missing_todos_dir_returns_empty(self, tmp_path):
        result = assemble_roadmap(str(tmp_path))
        assert result == []

    @pytest.mark.unit
    def test_empty_todos_dir_returns_empty(self, tmp_path):
        (tmp_path / "todos").mkdir()
        result = assemble_roadmap(str(tmp_path))
        assert result == []

    @pytest.mark.unit
    def test_roadmap_with_one_entry_returns_one_item(self, tmp_path):
        todos = tmp_path / "todos"
        todos.mkdir()
        (todos / "roadmap.yaml").write_text("- slug: my-feature\n  description: My feature\n")
        (todos / "my-feature").mkdir()
        result = assemble_roadmap(str(tmp_path))
        assert len(result) == 1
        assert isinstance(result[0], TodoInfo)
        assert result[0].slug == "my-feature"
        assert result[0].description == "My feature"


class TestSlugifyHeading:
    @pytest.mark.unit
    def test_simple_heading_lowercased_and_hyphenated(self):
        result = _slugify_heading("My Feature Title")
        assert result == "my-feature-title"

    @pytest.mark.unit
    def test_special_chars_replaced_with_hyphen(self):
        result = _slugify_heading("Feature: Add (OAuth)")
        assert result == "feature-add-oauth"

    @pytest.mark.unit
    def test_leading_trailing_hyphens_stripped(self):
        result = _slugify_heading("-Leading Trailing-")
        assert not result.startswith("-")
        assert not result.endswith("-")

    @pytest.mark.unit
    def test_numbers_preserved(self):
        result = _slugify_heading("Phase 2 Implementation")
        assert result == "phase-2-implementation"

    @pytest.mark.unit
    def test_already_slug_unchanged(self):
        result = _slugify_heading("my-feature")
        assert result == "my-feature"

    @pytest.mark.unit
    def test_multiple_spaces_collapsed(self):
        result = _slugify_heading("hello   world")
        assert result == "hello-world"
