"""Incremental JSONL transcript tailing primitives."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from teleclaude.core.models import JsonDict


@dataclass(frozen=True)
class TranscriptTailCursor:
    """Byte cursor for an append-only JSONL transcript file."""

    offset: int = 0
    partial_line: str = ""


@dataclass(frozen=True)
class TranscriptTailBatch:
    """New transcript entries read from a cursor position."""

    cursor: TranscriptTailCursor
    entries: list[JsonDict]


def read_appended_jsonl_entries(path: str | Path, cursor: TranscriptTailCursor) -> TranscriptTailBatch:
    """Read complete JSONL entries appended after ``cursor``."""

    transcript_path = Path(path)
    try:
        file_size = transcript_path.stat().st_size
    except OSError:
        return TranscriptTailBatch(cursor=cursor, entries=[])

    offset = cursor.offset if 0 <= cursor.offset <= file_size else 0
    partial_line = cursor.partial_line if offset == cursor.offset else ""

    try:
        with open(transcript_path, "rb") as f:
            f.seek(offset)
            new_bytes = f.read()
            next_offset = f.tell()
    except OSError:
        return TranscriptTailBatch(cursor=cursor, entries=[])

    if not new_bytes:
        return TranscriptTailBatch(cursor=TranscriptTailCursor(offset=offset, partial_line=partial_line), entries=[])

    text = partial_line + new_bytes.decode("utf-8", errors="ignore")
    complete_text = text
    next_partial = ""
    if not text.endswith(("\n", "\r")):
        line_break = max(text.rfind("\n"), text.rfind("\r"))
        if line_break == -1:
            complete_text = ""
            next_partial = text
        else:
            complete_text = text[: line_break + 1]
            next_partial = text[line_break + 1 :]

    entries: list[JsonDict] = []
    for line in complete_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            entry_value: object = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(entry_value, dict):
            entries.append(entry_value)

    return TranscriptTailBatch(
        cursor=TranscriptTailCursor(offset=next_offset, partial_line=next_partial),
        entries=entries,
    )
