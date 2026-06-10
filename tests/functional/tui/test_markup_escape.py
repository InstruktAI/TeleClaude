"""Regression: TUI notify calls must escape Rich markup in exception text."""

from __future__ import annotations

import pytest
from rich.text import Text

from teleclaude.cli.tui.utils.formatters import escape_markup

_PYDANTIC_ERROR_TEXT = (
    "1 validation error for TodoDumpRequest\n"
    "lifecycle_phase\n"
    "  Value error, [type=value_error, "
    "input_value='draft', "
    "input_type=dict]\n"
)

pytestmark = pytest.mark.functional


def test_unescaped_pydantic_error_loses_content_in_rich_markup():
    """Pydantic ValidationError bracket metadata is silently dropped by Rich markup parsing."""
    rendered = Text.from_markup(_PYDANTIC_ERROR_TEXT)
    assert rendered.plain != _PYDANTIC_ERROR_TEXT


def test_escape_markup_preserves_pydantic_error_content():
    """escape_markup makes Pydantic exception text safe and preserves all content."""
    escaped = escape_markup(_PYDANTIC_ERROR_TEXT)
    rendered = Text.from_markup(escaped)
    assert rendered.plain == _PYDANTIC_ERROR_TEXT
