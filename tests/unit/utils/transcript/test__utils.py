"""Characterization tests for teleclaude.utils.transcript._utils."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import teleclaude.utils.transcript._utils as transcript_utils

pytestmark = pytest.mark.unit


class TestParseTimestamp:
    @pytest.mark.parametrize(
        ("raw_timestamp", "expected_iso"),
        [
            ("2025-11-11T04:25:33.890Z", "2025-11-11T04:25:33.890000+00:00"),
            ("2025-11-11T04:25:33+00:00", "2025-11-11T04:25:33+00:00"),
            ("2025-11-11T04:25:33", "2025-11-11T04:25:33+00:00"),
        ],
    )
    def test_parses_supported_iso_shapes(self, raw_timestamp: str, expected_iso: str) -> None:
        parsed = transcript_utils._parse_timestamp(raw_timestamp)

        assert parsed is not None
        assert parsed.isoformat() == expected_iso

    def test_returns_none_for_invalid_timestamp(self) -> None:
        assert transcript_utils._parse_timestamp("not-a-timestamp") is None


class TestTimestampFormatting:
    def test_format_timestamp_prefix_uses_time_for_today_and_date_for_older_values(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            transcript_utils,
            "format_local_datetime",
            lambda dt, include_date=False: "DATE" if include_date else "TIME",
        )
        now = datetime.now(UTC)

        assert transcript_utils._format_timestamp_prefix(now) == "TIME · "
        assert transcript_utils._format_timestamp_prefix(now - timedelta(days=2)) == "DATE · "


class TestThinkingFormatting:
    def test_wrap_and_italicize_preserve_markdown_shapes(self) -> None:
        assert transcript_utils._wrap_thinking_emphasis("  plan  ") == "  *plan*  "
        assert transcript_utils._italicize_thinking_line("# Heading") == "# *Heading*"
        assert transcript_utils._italicize_thinking_line("1. Step") == "1. *Step*"
        assert transcript_utils._italicize_thinking_line("> Quote") == "> *Quote*"
        assert transcript_utils._italicize_thinking_line("| cell |") == "| cell |"
        assert transcript_utils._italicize_thinking_line("***") == "***"

    def test_format_thinking_preserves_code_blocks_and_trailing_blank_line(self) -> None:
        formatted = transcript_utils._format_thinking("thinking\n```python\nx = 1\n```\nnext")

        assert formatted == "*thinking*\n\n```python\nx = 1\n```\n*next*\n"


class TestTailLimiting:
    def test_apply_tail_limit_restarts_at_nearby_header(self) -> None:
        body = "older body" + ("x" * 8) + "\n## Recent\nbody"

        result = transcript_utils._apply_tail_limit(body, len("\n## Recent\nbody") + 5)

        assert result.startswith("[...truncated, showing last ")
        assert result.endswith("## Recent\nbody")

    def test_apply_tail_limit_codex_prefers_later_header_after_cutoff(self) -> None:
        truncated_window = ("x" * 20) + "\n## Earlier\nfirst" + ("y" * 450) + "\n## Later\nsecond"
        body = "prefix-" + truncated_window

        result = transcript_utils._apply_tail_limit_codex(body, len(truncated_window))

        assert "## Earlier" not in result
        assert result.endswith("## Later\nsecond")


class TestEscaping:
    def test_escape_triple_backticks_inserts_zero_width_space(self) -> None:
        assert transcript_utils._escape_triple_backticks("```python```") == "`\u200b``python`\u200b``"
