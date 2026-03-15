from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from teleclaude.cli.tui.utils import formatters


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz: object = None) -> _FixedDateTime:
        base = cls(2024, 1, 1, 12, 0, tzinfo=UTC)
        if tz is None:
            return base.replace(tzinfo=None)
        return base


@pytest.mark.unit
def test_relative_time_and_countdown_bucket_values_with_fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(formatters, "datetime", _FixedDateTime)

    assert formatters.format_relative_time("2024-01-01T12:00:00Z") == "0s"
    assert formatters.format_relative_time("2024-01-01T11:59:00Z") == "1m"
    assert formatters.format_relative_time("2024-01-01T11:00:00Z") == "1h"
    assert formatters.format_relative_time("2023-12-31T12:00:00Z") == "1d"
    assert formatters.format_relative_time("2024-01-01T12:01:00Z") == "now"
    assert formatters.format_countdown("2024-01-01T17:00:00Z") == "5h 0m"
    assert formatters.format_countdown("2024-01-01T12:10:00Z") == "10m"
    assert formatters.format_countdown("2024-01-01T11:59:00Z") == "soon"


@pytest.mark.unit
def test_path_and_text_helpers_match_current_shortening_rules() -> None:
    assert formatters.shorten_path("/Users/Morriz/project/trees/src/main.py", 20) == "...trees/src/main.py"
    assert formatters.shorten_path("/tmp/x", 20) == "/tmp/x"
    assert formatters.truncate_text("   a   b   c   ", 5) == "a b c"
    assert formatters.truncate_text("abcdef", 5) == "abcd…"


@pytest.mark.unit
def test_time_and_session_index_formatters_return_structured_values() -> None:
    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", formatters.format_time("2024-01-01T12:34:56Z"))
    assert formatters.session_display_index(3, "2") == "2.3"
    assert formatters.session_display_index(5) == "5"
