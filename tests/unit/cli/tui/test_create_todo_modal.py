"""Tests for CreateTodoModal slug validation."""

from __future__ import annotations

import pytest

from teleclaude.todo_scaffold import SLUG_PATTERN


def test_slug_pattern_accepts_valid_slugs() -> None:
    assert SLUG_PATTERN.match("my-todo")
    assert SLUG_PATTERN.match("simple")
    assert SLUG_PATTERN.match("a-b-c-123")
    assert SLUG_PATTERN.match("fix42")


def test_slug_pattern_rejects_invalid_slugs() -> None:
    assert not SLUG_PATTERN.match("Bad Slug")
    assert not SLUG_PATTERN.match("UPPER")
    assert not SLUG_PATTERN.match("-leading-dash")
    assert not SLUG_PATTERN.match("trailing-dash-")
    assert not SLUG_PATTERN.match("")
    assert not SLUG_PATTERN.match("has_underscore")
