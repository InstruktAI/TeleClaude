"""Unit tests for teleclaude.slug module."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.slug import SLUG_PATTERN, ensure_unique_slug, normalize_slug, validate_slug


class TestSlugPattern:
    def test_re_exported(self) -> None:
        assert SLUG_PATTERN is not None

    def test_valid_slugs(self) -> None:
        assert SLUG_PATTERN.match("my-todo")
        assert SLUG_PATTERN.match("simple")
        assert SLUG_PATTERN.match("a-b-c-123")
        assert SLUG_PATTERN.match("fix42")

    def test_invalid_slugs(self) -> None:
        assert not SLUG_PATTERN.match("Bad Slug")
        assert not SLUG_PATTERN.match("UPPER")
        assert not SLUG_PATTERN.match("-leading-dash")
        assert not SLUG_PATTERN.match("trailing-dash-")
        assert not SLUG_PATTERN.match("")


class TestValidateSlug:
    def test_accepts_valid_slug(self) -> None:
        validate_slug("my-todo")  # no raise

    def test_accepts_slug_with_numbers(self) -> None:
        validate_slug("fix-42")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="required"):
            validate_slug("")

    def test_rejects_whitespace_only(self) -> None:
        with pytest.raises(ValueError, match="required"):
            validate_slug("   ")

    def test_rejects_uppercase(self) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            validate_slug("Bad-Slug")

    def test_rejects_underscores(self) -> None:
        with pytest.raises(ValueError):
            validate_slug("has_underscore")

    def test_rejects_leading_dash(self) -> None:
        with pytest.raises(ValueError):
            validate_slug("-leading")

    def test_rejects_trailing_dash(self) -> None:
        with pytest.raises(ValueError):
            validate_slug("trailing-")

    def test_strips_whitespace_before_checking(self) -> None:
        validate_slug("  valid-slug  ")  # strips before checking — no raise


class TestNormalizeSlug:
    def test_basic_phrase(self) -> None:
        assert normalize_slug("Hello World") == "hello-world"

    def test_lowercases(self) -> None:
        assert normalize_slug("UPPER CASE") == "upper-case"

    def test_replaces_punctuation(self) -> None:
        assert normalize_slug("foo, bar! baz.") == "foo-bar-baz"

    def test_collapses_runs(self) -> None:
        assert normalize_slug("a  --  b") == "a-b"

    def test_strips_edges(self) -> None:
        assert normalize_slug("  -hello-  ") == "hello"

    def test_empty_string(self) -> None:
        assert normalize_slug("") == ""

    def test_only_punctuation(self) -> None:
        assert normalize_slug("!!!") == ""

    def test_numbers_preserved(self) -> None:
        assert normalize_slug("fix 42 bugs") == "fix-42-bugs"


class TestEnsureUniqueSlug:
    def test_no_collision_returns_slug(self, tmp_path: Path) -> None:
        assert ensure_unique_slug(tmp_path, "my-slug") == "my-slug"

    def test_single_collision_returns_suffix_2(self, tmp_path: Path) -> None:
        (tmp_path / "my-slug").mkdir()
        assert ensure_unique_slug(tmp_path, "my-slug") == "my-slug-2"

    def test_multiple_collisions(self, tmp_path: Path) -> None:
        (tmp_path / "my-slug").mkdir()
        (tmp_path / "my-slug-2").mkdir()
        assert ensure_unique_slug(tmp_path, "my-slug") == "my-slug-3"

    def test_many_collisions(self, tmp_path: Path) -> None:
        (tmp_path / "my-slug").mkdir()
        for i in range(2, 6):
            (tmp_path / f"my-slug-{i}").mkdir()
        assert ensure_unique_slug(tmp_path, "my-slug") == "my-slug-6"
