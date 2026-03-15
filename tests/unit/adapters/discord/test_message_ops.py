from __future__ import annotations

import pytest

from teleclaude.adapters.discord.message_ops import MessageOperationsMixin

pytestmark = pytest.mark.unit


class DummyMessageOperations(MessageOperationsMixin):
    def __init__(self, *, max_message_size: int) -> None:
        self.max_message_size = max_message_size
        self._TRUNCATION_SUFFIX = "..."

    def format_output(self, text: str, *, render_markdown: bool = False) -> str:
        return f"<<{text}>>"


def test_parse_optional_int_accepts_only_digit_strings() -> None:
    adapter = DummyMessageOperations(max_message_size=5)

    assert adapter._parse_optional_int(None) is None
    assert adapter._parse_optional_int("") is None
    assert adapter._parse_optional_int(" 42 ") == 42
    assert adapter._parse_optional_int("4.2") is None
    assert adapter._parse_optional_int("abc") is None


def test_split_message_chunks_prefers_newline_breaks_within_limit() -> None:
    adapter = DummyMessageOperations(max_message_size=5)

    assert adapter._split_message_chunks("line1\nline2") == ["line1", "line2"]


def test_split_message_chunks_falls_back_to_hard_splits_without_newlines() -> None:
    adapter = DummyMessageOperations(max_message_size=5)

    assert adapter._split_message_chunks("abcdef") == ["abcde", "f"]


def test_fit_message_text_truncates_with_suffix_until_suffix_exceeds_limit() -> None:
    adapter = DummyMessageOperations(max_message_size=5)

    assert adapter._fit_message_text("abcdefghij", context="message") == "ab..."

    adapter.max_message_size = 2

    assert adapter._fit_message_text("abcdefghij", context="message") == "ab"


def test_fit_output_to_limit_can_reduce_raw_output_to_empty_string() -> None:
    adapter = DummyMessageOperations(max_message_size=5)

    assert adapter._fit_output_to_limit("abcdef") == ""


def test_message_size_helpers_reflect_current_adapter_configuration() -> None:
    adapter = DummyMessageOperations(max_message_size=10)

    assert adapter.get_max_message_length() == 10
    assert adapter.get_ai_session_poll_interval() == 0.5
