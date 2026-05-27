"""Tests for teleclaude.config._coerce.as_bool."""

from __future__ import annotations

import pytest

from teleclaude.config._coerce import as_bool


@pytest.mark.unit
class TestAsBool:
    def test_passes_through_real_bools(self) -> None:
        assert as_bool(True) is True
        assert as_bool(False) is False

    def test_canonical_true_string(self) -> None:
        assert as_bool("True") is True

    def test_stringified_false_maps_to_false(self) -> None:
        # The critical path: "False" must not become bool("False") == True.
        assert as_bool("False") is False

    def test_none_uses_default(self) -> None:
        assert as_bool(None) is False
        assert as_bool(None, default=True) is True

    def test_non_boolean_raises(self) -> None:
        with pytest.raises(ValueError):
            as_bool("maybe")
