"""Characterization tests for incremental transcript tailing."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.utils.transcript import TranscriptTailCursor, read_appended_jsonl_entries
from teleclaude.utils.transcript.tailer import TranscriptTailReadError


def test_read_appended_jsonl_entries_advances_from_cursor(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"first": 1}\n', encoding="utf-8")
    cursor = TranscriptTailCursor(offset=transcript.stat().st_size)
    with open(transcript, "a", encoding="utf-8") as f:
        f.write('{"second": 2}\n')

    batch = read_appended_jsonl_entries(transcript, cursor)

    assert batch.entries == [{"second": 2}]
    assert batch.cursor == TranscriptTailCursor(offset=transcript.stat().st_size)


def test_read_appended_jsonl_entries_holds_incomplete_trailing_line(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"partial": ', encoding="utf-8")

    first_batch = read_appended_jsonl_entries(transcript, TranscriptTailCursor())
    with open(transcript, "a", encoding="utf-8") as f:
        f.write("true}\n")
    second_batch = read_appended_jsonl_entries(transcript, first_batch.cursor)

    assert first_batch.entries == []
    assert second_batch.entries == [{"partial": True}]


def test_read_appended_jsonl_entries_raises_on_read_failure(tmp_path: Path) -> None:
    transcript = tmp_path / "missing.jsonl"

    with pytest.raises(TranscriptTailReadError):
        read_appended_jsonl_entries(transcript, TranscriptTailCursor())
