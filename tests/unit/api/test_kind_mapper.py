"""Tests for teleclaude.api.kind_mapper — v1 kind → canonical kind mapping."""

from __future__ import annotations

import pytest

from teleclaude.api.kind_mapper import (
    KIND_BUG,
    KIND_FEATURE,
    KIND_MIGRATION,
    KIND_PREPPED,
    KIND_REFACTOR,
    KIND_TODO,
    map_v1_kind_to_canonical,
)


class TestMapV1KindToCanonical:
    @pytest.mark.unit
    def test_none_maps_to_feature(self) -> None:
        assert map_v1_kind_to_canonical(None) == KIND_FEATURE

    @pytest.mark.unit
    def test_empty_string_maps_to_feature(self) -> None:
        assert map_v1_kind_to_canonical("") == KIND_FEATURE

    @pytest.mark.unit
    def test_bug_maps_to_bug(self) -> None:
        assert map_v1_kind_to_canonical("bug") == KIND_BUG

    @pytest.mark.unit
    def test_prepped_passes_through(self) -> None:
        assert map_v1_kind_to_canonical("prepped") == KIND_PREPPED

    @pytest.mark.unit
    def test_draft_maps_to_feature(self) -> None:
        assert map_v1_kind_to_canonical("draft") == KIND_FEATURE

    @pytest.mark.unit
    def test_canonical_feature_passes_through(self) -> None:
        assert map_v1_kind_to_canonical("feature") == KIND_FEATURE

    @pytest.mark.unit
    def test_canonical_refactor_passes_through(self) -> None:
        assert map_v1_kind_to_canonical("refactor") == KIND_REFACTOR

    @pytest.mark.unit
    def test_canonical_migration_passes_through(self) -> None:
        assert map_v1_kind_to_canonical("migration") == KIND_MIGRATION

    @pytest.mark.unit
    def test_canonical_todo_passes_through(self) -> None:
        assert map_v1_kind_to_canonical("todo") == KIND_TODO
