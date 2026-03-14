"""Transcript iteration: load JSONL entries, detect turn boundaries, resolve agent entries."""

from __future__ import annotations

import json
import logging
import os
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from teleclaude.core.agents import AgentName
from teleclaude.core.models import JsonDict

from ._parsers import normalize_transcript_entry_message
from ._utils import CHECKPOINT_JSONL_TAIL_READ_BYTES, _parse_timestamp

logger = logging.getLogger(__name__)

__all__ = [
    "_entry_role",
    "_get_entries_for_agent",
    "_is_rotation_fallback_candidate",
    "_iter_claude_entries",
    "_iter_codex_entries",
    "_iter_gemini_entries",
    "_iter_jsonl_entries",
    "_iter_jsonl_entries_tail",
    "_start_index_after_timestamp_or_rotation",
]


def _iter_jsonl_entries(
    path: Path,
) -> Iterable[JsonDict]:
    """Yield JSON objects for each line in a transcript file."""

    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                entry_value: object = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(entry_value, dict):
                yield cast(JsonDict, entry_value)


def _iter_jsonl_entries_tail(
    path: Path,
    max_entries: int,
    *,
    max_bytes: int = CHECKPOINT_JSONL_TAIL_READ_BYTES,
) -> Iterable[JsonDict]:
    """Yield only the last N JSONL entries from a transcript file."""
    if max_entries <= 0 or max_bytes <= 0:
        return

    try:
        file_size = path.stat().st_size
    except OSError:
        return

    read_bytes = min(file_size, max_bytes)
    if read_bytes <= 0:
        return

    try:
        with open(path, "rb") as f:
            if file_size > read_bytes:
                f.seek(-read_bytes, os.SEEK_END)
            raw_tail = f.read(read_bytes)
    except OSError:
        return

    if not raw_tail:
        return

    tail_text = raw_tail.decode("utf-8", errors="ignore")
    # If we started mid-file, drop the potentially partial first line.
    if file_size > read_bytes:
        first_newline = tail_text.find("\n")
        if first_newline == -1:
            return
        tail_text = tail_text[first_newline + 1 :]

    tail = deque(maxlen=max_entries)  # type: ignore[var-annotated]
    for line in tail_text.splitlines():
        if not line.strip():
            continue
        try:
            entry_value: object = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry_value, dict):
            tail.append(cast(JsonDict, entry_value))

    yield from tail


def _iter_claude_entries(
    path: Path,
    *,
    tail_entries: int | None = None,
) -> Iterable[JsonDict]:
    """Yield entries from Claude Code transcripts (raw JSONL)."""

    if tail_entries is not None:
        yield from _iter_jsonl_entries_tail(path, tail_entries)
        return
    yield from _iter_jsonl_entries(path)


def _iter_codex_entries(
    path: Path,
    *,
    tail_entries: int | None = None,
) -> Iterable[JsonDict]:
    """Yield entries from Codex JSONL transcripts, skipping metadata.

    guard: allow-string-compare
    """

    source = _iter_jsonl_entries_tail(path, tail_entries) if tail_entries is not None else _iter_jsonl_entries(path)
    for entry in source:
        if entry.get("type") == "session_meta":
            continue
        yield entry


def _coerce_dict_list(raw_items: object) -> list[JsonDict]:
    """Return only dict items from an external JSON array."""
    if not isinstance(raw_items, list):
        return []
    return [cast(JsonDict, item) for item in raw_items if isinstance(item, dict)]


def _load_gemini_document(path: Path) -> JsonDict:
    """Load Gemini session JSON as a dict when possible."""
    with open(path, encoding="utf-8") as f:
        raw_document: object = json.load(f)
    if isinstance(raw_document, dict):
        return cast(JsonDict, raw_document)
    return {}


def _normalize_gemini_user_entry(message: JsonDict) -> JsonDict:
    """Normalize a Gemini user message into transcript entry shape."""
    content_value = message.get("content", "")
    return {
        "type": "user",
        "timestamp": message.get("timestamp"),
        "message": {
            "role": "user",
            "content": [{"type": "input_text", "text": str(content_value)}],
        },
    }


def _extract_gemini_tool_result_texts(tool_call: JsonDict) -> list[str]:
    """Collect tool result output strings from a Gemini tool call."""
    result_texts: list[str] = []
    for result in _coerce_dict_list(tool_call.get("result")):
        function_response = result.get("functionResponse")
        response_candidate = (
            function_response.get("response") if isinstance(function_response, dict) else result.get("response")
        )

        response_value = None
        if isinstance(response_candidate, dict):
            response_value = response_candidate.get("output")
        elif response_candidate:
            response_value = response_candidate

        if response_value:
            result_texts.append(str(response_value))

    fallback_text = tool_call.get("resultDisplay") or tool_call.get("description")
    if fallback_text and not result_texts:
        result_texts.append(str(fallback_text))
    return result_texts


def _build_gemini_assistant_blocks(
    message: JsonDict,
) -> list[JsonDict]:
    """Build normalized assistant blocks from a Gemini message."""
    blocks: list[JsonDict] = []

    for thought in _coerce_dict_list(message.get("thoughts")):
        description = thought.get("description") or thought.get("text") or ""
        if description:
            blocks.append({"type": "thinking", "thinking": description})

    content_text = message.get("content")
    if content_text:
        blocks.append({"type": "text", "text": str(content_text)})

    for tool_call in _coerce_dict_list(message.get("toolCalls")):
        name = tool_call.get("displayName") or tool_call.get("name") or "tool"
        args = tool_call.get("args")
        input_payload: JsonDict = {}
        if isinstance(args, dict):
            input_payload = cast(JsonDict, args)  # type: ignore[redundant-cast]
        blocks.append({"type": "tool_use", "name": name, "input": input_payload})

        result_texts = _extract_gemini_tool_result_texts(tool_call)
        if any(result_texts):
            blocks.append({"type": "tool_result", "content": "\n\n".join(result_texts)})

    return blocks


def _iter_gemini_entries(
    path: Path,
) -> Iterable[JsonDict]:
    """Yield normalized entries from Gemini JSON session files.

    guard: allow-string-compare
    """

    document = _load_gemini_document(path)
    for message in _coerce_dict_list(document.get("messages", [])):
        msg_type = message.get("type")

        if msg_type == "user":
            yield _normalize_gemini_user_entry(message)
            continue

        if msg_type != "gemini":
            continue

        blocks = _build_gemini_assistant_blocks(message)
        if not blocks:
            continue

        yield cast(
            JsonDict,
            {
                "type": "assistant",
                "timestamp": message.get("timestamp"),
                "message": {
                    "role": "assistant",
                    "content": blocks,
                },
            },
        )


def _entry_role(entry: Mapping[str, object]) -> str | None:
    """Return normalized role from an entry's message/payload."""
    message = normalize_transcript_entry_message(entry)
    if isinstance(message, dict):
        role = message.get("role")
        if isinstance(role, str):
            return role
    return None


def _is_rotation_fallback_candidate(entries: Sequence[Mapping[str, object]]) -> bool:
    """Detect transcript rotation window with assistant output but no user boundary."""
    saw_user = False
    saw_assistant = False
    for entry in entries:
        role = _entry_role(entry)
        if role == "user":
            saw_user = True
        elif role == "assistant":
            saw_assistant = True
    return saw_assistant and not saw_user


def _start_index_after_timestamp_or_rotation(
    entries: Sequence[Mapping[str, object]],
    since_timestamp: datetime,
    *,
    transcript_path: str,
    agent_name: AgentName,
    mode: str,
) -> int | None:
    """Return first entry index after cursor; fallback to start for rotation windows."""
    if since_timestamp.tzinfo is None:
        since_timestamp = since_timestamp.replace(tzinfo=UTC)

    for i, entry in enumerate(entries):
        entry_ts_str = entry.get("timestamp")
        if isinstance(entry_ts_str, str):
            entry_dt = _parse_timestamp(entry_ts_str)
            if entry_dt:
                if entry_dt.tzinfo is None:
                    entry_dt = entry_dt.replace(tzinfo=UTC)
                if entry_dt > since_timestamp:
                    return i

    if _is_rotation_fallback_candidate(entries):
        logger.info(
            "Rotation fallback in transcript extraction: mode=%s agent=%s path=%s entries=%d since=%s",
            mode,
            agent_name.value,
            transcript_path,
            len(entries),
            since_timestamp.isoformat(),
        )
        return 0
    return None


def _get_entries_for_agent(
    transcript_path: str,
    agent_name: AgentName,
    *,
    tail_entries: int | None = None,
) -> list[JsonDict] | None:
    """Load and return transcript entries for the given agent type.

    Returns None if path doesn't exist or agent type is unknown.
    """
    path = Path(transcript_path).expanduser()
    if not path.exists():
        return None

    if agent_name == AgentName.CLAUDE:
        return list(_iter_claude_entries(path, tail_entries=tail_entries))
    if agent_name == AgentName.GEMINI:
        return list(_iter_gemini_entries(path))
    if agent_name == AgentName.CODEX:
        return list(_iter_codex_entries(path, tail_entries=tail_entries))
    return None  # type: ignore[unreachable]  # Defensive fallback
