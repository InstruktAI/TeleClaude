from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.adapters.discord.message_ops import MessageOperationsMixin

pytestmark = pytest.mark.unit


class DummyMessageOperations(MessageOperationsMixin):
    def __init__(self, *, max_message_size: int) -> None:
        self.max_message_size = max_message_size
        self._TRUNCATION_SUFFIX = "..."
        self.destination = SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(id="discord-file")))
        self._discord = SimpleNamespace(
            File=MagicMock(side_effect=lambda file_path: SimpleNamespace(file_path=file_path))
        )

    def format_output(self, text: str, *, render_markdown: bool = False) -> str:
        return f"<<{text}>>"

    async def _resolve_destination_channel(
        self,
        session: object,
        *,
        metadata: object | None = None,
    ) -> object:
        _ = (session, metadata)
        return self.destination

    @staticmethod
    def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]:
        _ = label
        if not callable(fn):
            raise TypeError
        return cast("Callable[..., Awaitable[object]]", fn)


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


def test_split_message_chunks_packs_full_lines_until_next_line_would_overflow() -> None:
    adapter = DummyMessageOperations(max_message_size=10)

    assert adapter._split_message_chunks("1234\n5678\n90") == ["1234\n5678", "90"]


def test_split_message_chunks_uses_space_when_no_newline_fits() -> None:
    adapter = DummyMessageOperations(max_message_size=5)

    chunks = adapter._split_message_chunks("abcd efgh")

    assert len(chunks) == 2
    assert all(len(chunk) <= adapter.max_message_size for chunk in chunks)


def test_split_message_chunks_uses_hard_split_when_no_separator_fits() -> None:
    adapter = DummyMessageOperations(max_message_size=5)

    chunks = adapter._split_message_chunks("abcdefgh")

    assert len(chunks) == 2
    assert all(len(chunk) <= adapter.max_message_size for chunk in chunks)


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


@pytest.mark.asyncio
async def test_send_file_uses_discord_attachment_payload(tmp_path: Path) -> None:
    adapter = DummyMessageOperations(max_message_size=100)
    file_path = tmp_path / "report.txt"
    file_path.write_text("payload", encoding="utf-8")
    session = SimpleNamespace(session_id="sess-file")

    result = await adapter.send_file(session, str(file_path), caption="Quarterly report")

    assert result == "discord-file"
    adapter._discord.File.assert_called_once_with(str(file_path))
    adapter.destination.send.assert_awaited_once()
    call = adapter.destination.send.await_args
    assert call.kwargs["content"] == "Quarterly report"
    assert call.kwargs["file"].file_path == str(file_path)
