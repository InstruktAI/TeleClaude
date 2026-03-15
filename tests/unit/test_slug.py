"""Characterization tests for teleclaude.slug."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.slug import ensure_unique_slug, normalize_slug, validate_slug


def test_validate_slug_accepts_trimmed_valid_values() -> None:
    validate_slug("  valid-slug-2  ")


@pytest.mark.parametrize("value", ["", "   ", "MixedCase", "under_score", "double--dash", "-leading"])
def test_validate_slug_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        validate_slug(value)


def test_normalize_slug_lowercases_replaces_runs_and_trims_hyphens() -> None:
    assert normalize_slug("  Hello, World! -- 2024  ") == "hello-world-2024"


def test_ensure_unique_slug_returns_original_when_path_is_free(tmp_path: Path) -> None:
    assert ensure_unique_slug(tmp_path, "project-alpha") == "project-alpha"


def test_ensure_unique_slug_skips_taken_suffixes_until_a_free_name_exists(tmp_path: Path) -> None:
    (tmp_path / "project-alpha").mkdir()
    (tmp_path / "project-alpha-2").mkdir()
    (tmp_path / "project-alpha-3").mkdir()

    assert ensure_unique_slug(tmp_path, "project-alpha") == "project-alpha-4"
