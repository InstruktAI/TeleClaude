"""Transcript iteration: load JSONL entries, detect turn boundaries, resolve agent entries."""

from __future__ import annotations

import io
import json
import os
import re
from bisect import bisect_right
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import cast

import zstandard
from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName
from teleclaude.core.models import JsonDict, JsonValue
from teleclaude.core.session_transcript import SessionTranscript

from ._checkpoint_anchors import find_last_checkpoint_anchor
from ._parsers import normalize_transcript_entry_message
from ._turn_completion import TURN_COMPLETION_TAIL_ENTRIES, claude_turn_completion, codex_turn_completion
from ._user_turns import find_last_turn_start, is_turn_start_entry
from ._utils import CHECKPOINT_JSONL_TAIL_READ_BYTES, _apply_tail_limit, _apply_tail_limit_codex, _parse_timestamp
from .source_views import TranscriptEntries, read_transcript_entries

logger = get_logger(__name__)

_REPORTED_TRANSCRIPT_FORMAT_MISMATCHES: set[tuple[str, str]] = set()
_FORMAT_MISMATCH_SINK: ContextVar[Callable[[str, Path, json.JSONDecodeError], None] | None] = ContextVar(
    "transcript_format_mismatch_sink", default=None
)
_GEMINI_MESSAGES_FIELD = "messages"
_CODEX_RECORD_TYPE_FIELD = "type"
_CODEX_SESSION_META_TYPE = "session_meta"


@contextmanager
def collect_transcript_format_mismatches(
    sink: Callable[[str, Path, json.JSONDecodeError], None] | None,
) -> Iterator[None]:
    """Bind an explicit caller-owned sink for mismatches found in this parse."""
    token = _FORMAT_MISMATCH_SINK.set(sink)
    try:
        yield
    finally:
        _FORMAT_MISMATCH_SINK.reset(token)


def _report_transcript_format_mismatch(agent: str, path: Path, exc: json.JSONDecodeError) -> None:
    """Report third-party transcript shape drift exactly once per (agent, path).

    External agent CLIs (Gemini, Codex) change their on-disk session-state format without
    a stability contract. When our reader can't parse a transcript, that is a high-signal
    integration-drift event: the agent shipped a new shape and our parser is now stale.
    The active parse owner can collect this diagnostic and publish it through its
    awaited runtime error boundary. Parsers with no such owner still log it.
    """
    key = (agent, str(path))
    if key in _REPORTED_TRANSCRIPT_FORMAT_MISMATCHES:
        return
    _REPORTED_TRANSCRIPT_FORMAT_MISMATCHES.add(key)
    logger.warning(
        "Transcript format mismatch — third-party CLI may have changed shape",
        agent=agent,
        path=str(path),
        error=str(exc),
    )
    sink = _FORMAT_MISMATCH_SINK.get()
    if sink is not None:
        try:
            sink(agent, path, exc)
        except Exception as sink_exc:
            logger.debug("Transcript mismatch reporting failed (non-fatal): %s", sink_exc)


__all__ = [
    "TRANSCRIPT_READERS",
    "TranscriptReader",
    "_entry_role",
    "_get_checkpoint_entries_for_agent",
    "_get_entries_for_agent",
    "_is_rotation_fallback_candidate",
    "_iter_claude_entries",
    "_iter_codex_entries",
    "_iter_gemini_entries",
    "_iter_jsonl_entries",
    "_iter_jsonl_entries_tail",
    "_iter_jsonl_entry_windows",
    "_start_index_after_timestamp_or_rotation",
    "read_turn_completion",
]


@dataclass(frozen=True)
class _JsonlEntryWindow:
    """A chronological JSONL suffix plus whether it reaches the file start."""

    entries: tuple[JsonDict, ...]
    at_beginning: bool


def _parse_jsonl_lines(lines: Iterable[str]) -> Iterable[JsonDict]:
    """Yield JSON-object lines while preserving malformed-line tolerance."""
    for line in lines:
        if not line.strip():
            continue
        try:
            entry_value: object = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry_value, dict):
            yield cast(JsonDict, entry_value)


def _iter_jsonl_entries(
    path: Path,
) -> Iterable[JsonDict]:
    """Yield JSON objects for each line in a transcript file."""

    with open(path, encoding="utf-8") as f:
        yield from _parse_jsonl_lines(f)


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

    tail = deque(_parse_jsonl_lines(tail_text.splitlines()), maxlen=max_entries)

    yield from tail


def _iter_jsonl_entry_windows(
    path: Path,
    *,
    initial_bytes: int = CHECKPOINT_JSONL_TAIL_READ_BYTES,
) -> Iterable[_JsonlEntryWindow]:
    """Yield geometrically growing complete-record JSONL suffixes from one fixed EOF."""
    if initial_bytes <= 0:
        return

    try:
        with open(path, "rb") as f:
            end_offset = os.fstat(f.fileno()).st_size
            if end_offset <= 0:
                yield _JsonlEntryWindow(entries=(), at_beginning=True)
                return

            offset = end_offset
            window_bytes = min(initial_bytes, end_offset)
            leading_partial = b""
            entries: deque[JsonDict] = deque()

            while offset > 0:
                start_offset = max(0, end_offset - window_bytes)
                f.seek(start_offset)
                chunk = f.read(offset - start_offset)
                if not chunk:
                    return

                raw_window = chunk + leading_partial
                starts_at_record_boundary = start_offset == 0
                if not starts_at_record_boundary:
                    f.seek(start_offset - 1)
                    starts_at_record_boundary = f.read(1) == b"\n"

                complete_bytes = raw_window
                if not starts_at_record_boundary:
                    first_newline = raw_window.find(b"\n")
                    if first_newline == -1:
                        leading_partial = raw_window
                        complete_bytes = b""
                    else:
                        leading_partial = raw_window[: first_newline + 1]
                        complete_bytes = raw_window[first_newline + 1 :]
                else:
                    leading_partial = b""

                parsed = list(_parse_jsonl_lines(complete_bytes.decode("utf-8", errors="ignore").splitlines()))
                entries.extendleft(reversed(parsed))
                yield _JsonlEntryWindow(entries=tuple(entries), at_beginning=start_offset == 0)

                offset = start_offset
                window_bytes = min(end_offset, window_bytes * 2)
    except OSError:
        return


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


def _is_turn_aborted_event(entry: JsonDict) -> bool:
    """Return True when entry is a Codex turn_aborted event_msg."""
    if entry.get("type") != "event_msg":
        return False
    payload = entry.get("payload")
    return isinstance(payload, dict) and payload.get("type") == "turn_aborted"


def _strip_turn_aborted_text(entry: JsonDict) -> JsonDict | None:
    """Strip Codex-injected <turn_aborted> blocks from a user message.

    Returns the cleaned entry, or None if the message is empty after stripping.
    """
    payload = entry.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "message" or payload.get("role") != "user":
        return entry

    content = payload.get("content")
    if not isinstance(content, list):
        return entry

    cleaned_content: list[JsonDict] = []
    for block_raw in content:
        if not isinstance(block_raw, dict):
            continue
        text = block_raw.get("text")
        if not isinstance(text, str):
            cleaned_content.append(block_raw)
            continue
        stripped = re.sub(r"<turn_aborted>.*?</turn_aborted>\s*", "", text, flags=re.DOTALL).strip()
        if stripped:
            cleaned_content.append({**block_raw, "text": stripped})

    if not cleaned_content:
        return None
    return cast(JsonDict, {**entry, "payload": {**payload, "content": cleaned_content}})


def _normalize_codex_entries(source: Iterable[JsonDict]) -> Iterable[JsonDict]:
    """Normalize Codex JSONL entries, skipping metadata.

    Buffers one entry so that when a turn_aborted event_msg is encountered,
    the preceding Codex-injected user message can be cleaned.

    guard: allow-string-compare
    """

    pending: JsonDict | None = None
    for entry in source:
        if entry.get("type") == "session_meta":
            continue

        if _is_turn_aborted_event(entry):
            # The preceding buffered entry is the synthetic user message — clean it.
            if pending is not None:
                cleaned = _strip_turn_aborted_text(pending)
                if cleaned is not None:
                    yield cleaned
                pending = None
            # Drop the event_msg itself.
            continue

        if pending is not None:
            yield pending
        pending = entry

    if pending is not None:
        yield pending


def _iter_codex_entries(
    path: Path,
    *,
    tail_entries: int | None = None,
) -> Iterable[JsonDict]:
    """Yield normalized entries from Codex JSONL transcripts."""
    source = _iter_jsonl_entries_tail(path, tail_entries) if tail_entries is not None else _iter_jsonl_entries(path)
    yield from _normalize_codex_entries(source)


def _coerce_dict_list(raw_items: object) -> list[JsonDict]:
    """Return only dict items from an external JSON array."""
    if not isinstance(raw_items, list):
        return []
    return [cast(JsonDict, item) for item in raw_items if isinstance(item, dict)]


def _iter_gemini_records(path: Path) -> Iterable[JsonDict]:
    """Yield raw Gemini message records from either JSONL (0.41+) or legacy JSON sessions.

    Gemini CLI switched its session-state file from a single JSON document with
    ``{"messages": [...]}`` to JSONL with no envelope around May 2026 (and bumped the
    file extension from ``.json`` to ``.jsonl``). Branch on extension so both shapes
    keep working — legacy ``.json`` fixtures stay valid, current ``.jsonl`` files parse.
    """
    if path.suffix == ".jsonl":
        yielded_record = False
        first_decode_error: json.JSONDecodeError | None = None
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record: object = json.loads(line)
                except json.JSONDecodeError as exc:
                    if first_decode_error is None:
                        first_decode_error = exc
                    continue
                if isinstance(record, dict):
                    yielded_record = True
                    yield cast(JsonDict, record)
        if not yielded_record and first_decode_error is not None:
            _report_transcript_format_mismatch("gemini", path, first_decode_error)
        return

    try:
        with open(path, encoding="utf-8") as f:
            raw_document: object = json.load(f)
    except json.JSONDecodeError as exc:
        _report_transcript_format_mismatch("gemini", path, exc)
        return
    if not isinstance(raw_document, dict):
        return
    yield from _coerce_dict_list(raw_document.get("messages", []))


def _normalize_gemini_user_entry(message: JsonDict) -> JsonDict:
    """Normalize a Gemini user message into transcript entry shape."""
    content_value = message.get("content", "")
    # Gemini stores user content as [{"text": "..."}] — extract the text.
    if isinstance(content_value, list):
        parts = []
        for item in content_value:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        content_value = "\n".join(parts) if parts else str(content_value)
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
        blocks.append({"type": "pre_tool_use", "name": name, "input": input_payload})

        result_texts = _extract_gemini_tool_result_texts(tool_call)
        if any(result_texts):
            blocks.append({"type": "tool_result", "content": "\n\n".join(result_texts)})

    return blocks


# Antigravity CLI (agy) transcript records are tagged by an uppercase ``source``
# enum rather than the legacy ``type: user|gemini`` discriminator.
_AGY_SOURCES: frozenset[str] = frozenset({"USER_EXPLICIT", "MODEL", "SYSTEM"})
_AGY_STEP_TYPE_FIELD = "type"
_AGY_GENERIC_STEP_TYPE = "GENERIC"
AGY_STEP_STATUS_FIELD = "agy_step_status"


class AntigravityStepStatus(StrEnum):
    """Closed result vocabulary carried by Antigravity generic steps."""

    DONE = "DONE"
    ERROR = "ERROR"
    RUNNING = "RUNNING"


_AGY_STEP_STATUS_VALUES = frozenset(status.value for status in AntigravityStepStatus)
_AGY_USER_REQUEST_RE = re.compile(r"<USER_REQUEST>(.*?)</USER_REQUEST>", re.DOTALL)


def _extract_agy_user_request(content: object) -> str:
    """Pull the user's text out of an agy USER_INPUT envelope.

    agy wraps the prompt in ``<USER_REQUEST>...</USER_REQUEST>`` and appends
    ``<ADDITIONAL_METADATA>`` / ``<USER_SETTINGS_CHANGE>`` blocks; only the
    request body is the user's input.
    """
    if not isinstance(content, str):
        return ""
    match = _AGY_USER_REQUEST_RE.search(content)
    text = match.group(1) if match else content
    return text.strip()


def _clean_agy_tool_args(args: JsonDict) -> JsonDict:
    """Unwrap agy's JSON-stringified tool-arg values (e.g. ``'"\\"/path\\""'``)."""
    cleaned: JsonDict = {}
    for key, value in args.items():
        if isinstance(value, str):
            try:
                cleaned[key] = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                cleaned[key] = value
        else:
            cleaned[key] = value
    return cleaned


def _build_agy_assistant_blocks(message: JsonDict) -> list[JsonDict]:
    """Build normalized assistant blocks from an agy MODEL-source record."""
    blocks: list[JsonDict] = []

    thinking = message.get("thinking")
    if isinstance(thinking, str) and thinking.strip():
        blocks.append({"type": "thinking", "thinking": thinking})

    content = message.get("content")
    if isinstance(content, str) and content.strip():
        blocks.append({"type": "text", "text": content})

    for tool_call in _coerce_dict_list(message.get("tool_calls")):
        name = tool_call.get("name") or "tool"
        args = tool_call.get("args")
        input_payload = _clean_agy_tool_args(args) if isinstance(args, dict) else {}
        blocks.append({"type": "pre_tool_use", "name": name, "input": input_payload})

    return blocks


def _normalize_agy_entry(message: JsonDict) -> JsonDict | None:
    """Normalize an agy transcript record into a transcript entry, or None to skip.

    SYSTEM-source records (conversation history, system messages, checkpoints)
    are not user/assistant turns and are skipped.
    """
    source = message.get("source")
    timestamp = message.get("created_at")

    if source == "USER_EXPLICIT":
        text = _extract_agy_user_request(message.get("content"))
        if not text:
            return None
        return cast(
            JsonDict,
            {
                "type": "user",
                "timestamp": timestamp,
                "message": {"role": "user", "content": [{"type": "input_text", "text": text}]},
            },
        )

    if source == "MODEL":
        blocks = _build_agy_assistant_blocks(message)
        if not blocks:
            return None
        entry = cast(
            JsonDict,
            {
                "type": "assistant",
                "timestamp": timestamp,
                "message": {"role": "assistant", "content": blocks},
            },
        )
        if message.get(_AGY_STEP_TYPE_FIELD) == _AGY_GENERIC_STEP_TYPE:
            status = message.get("status")
            if isinstance(status, str) and status in _AGY_STEP_STATUS_VALUES:
                entry[AGY_STEP_STATUS_FIELD] = status
        return entry

    return None


def _iter_gemini_entries(
    path: Path,
) -> Iterable[JsonDict]:
    """Read and normalize Gemini/agy records through the native format reader."""
    yield from _normalize_gemini_entries(_iter_gemini_records(path))


def _normalize_gemini_entries(records: Iterable[JsonDict]) -> Iterable[JsonDict]:
    """Yield normalized entries from Gemini/agy session files.

    Routes each record by schema: agy records carry an uppercase ``source``
    discriminator (``USER_EXPLICIT``/``MODEL``/``SYSTEM``); legacy Gemini
    records use ``type: user|gemini``.

    guard: allow-string-compare
    """

    for message in records:
        if message.get("source") in _AGY_SOURCES:
            entry = _normalize_agy_entry(message)
            if entry is not None:
                yield entry
            continue

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


def _is_rotation_fallback_candidate(
    entries: Sequence[Mapping[str, object]],
    agent_name: AgentName | None = None,
) -> bool:
    """Detect transcript rotation window with assistant output but no user boundary."""
    saw_user = False
    saw_assistant = False
    for entry in entries:
        entry_dict = cast(JsonDict, entry) if isinstance(entry, dict) else {}
        role = _entry_role(entry)
        if is_turn_start_entry(entry_dict, agent_name):
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

    if isinstance(entries, TranscriptEntries) and tuple(entries) == entries.snapshot:
        index = bisect_right(entries.timestamp_maxima, since_timestamp)
        if index < len(entries):
            return index
    else:
        for i, entry in enumerate(entries):
            entry_ts_str = entry.get("timestamp")
            if isinstance(entry_ts_str, str):
                entry_dt = _parse_timestamp(entry_ts_str)
                if entry_dt:
                    if entry_dt.tzinfo is None:
                        entry_dt = entry_dt.replace(tzinfo=UTC)
                    if entry_dt > since_timestamp:
                        return i

    if _is_rotation_fallback_candidate(entries, agent_name):
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


_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def _dsh_event_timestamp(event: Mapping[str, object]) -> str | None:
    """Convert a DSH envelope ``time`` (epoch milliseconds) to ISO-8601 UTC.

    Every non-``session`` DSH event carries a monotonic ``time`` field (epoch
    milliseconds) alongside ``seq``. Normalizing it to the same ISO-8601 UTC
    string the other agent iterators emit lets the shared projection
    watermark/cursor machinery treat DeepSeek transcripts exactly like Claude,
    Codex, and Gemini transcripts.
    """
    raw = event.get("time")
    if not isinstance(raw, (int, float)):
        return None
    try:
        instant = datetime.fromtimestamp(raw / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return instant.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _iter_deepseek_entries(path: Path) -> Iterable[JsonDict]:
    """Read and normalize native DeepSeek records."""
    yield from _normalize_deepseek_entries(_read_dsh_records(path))


def _read_dsh_records(path: Path) -> Iterable[JsonDict]:
    """Decode native DeepSeek JSONL records for uncached historical readers."""
    for line in _read_dsh_session_lines(path):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield cast(JsonDict, event)


def _normalize_deepseek_entries(records: Iterable[JsonDict]) -> Iterable[JsonDict]:
    """Yield DeepSeek Harness session events normalized to the shared entry shape.

    DSH persists one JSON object per line ({"seq", "time", "type", "data"}) in
    a zstd-compressed artifact (session.jsonl.zstd) by default. The tool-call
    extractor consumes message entries whose content carries pre_tool_use /
    tool_result blocks, plus user entries for turn boundaries, so:

      - user/message      -> {"type": "user", "message": {...}}
      - assistant/message -> content blocks mapped (tool-call -> pre_tool_use)
      - tool/result       -> tool_result entry
      - tool/call         -> fallback pre_tool_use entry (arguments is a JSON string)

    Each normalized entry carries the envelope's ``time`` as an ISO-8601 UTC
    ``timestamp`` so the shared projection watermark advances per event instead
    of re-projecting the whole transcript on every pass.
    """
    for event in records:
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        timestamp = _dsh_event_timestamp(event)
        event_type = event.get("type")
        if event_type == "user/message":
            message = _normalize_dsh_message(data)
            if message is not None:
                yield {"type": "user", "message": message, "timestamp": timestamp}
        elif event_type == "assistant/message":
            message = _normalize_dsh_message(data.get("message"))
            if message is not None:
                yield {"type": "assistant", "message": message, "timestamp": timestamp}
        elif event_type == "tool/call":
            yield _dsh_tool_call_entry(data, timestamp=timestamp)
        elif event_type == "tool/result":
            entry = _dsh_tool_result_entry(data, timestamp=timestamp)
            if entry is not None:
                yield entry


def _read_dsh_session_lines(path: Path) -> Iterable[str]:
    """Yield JSONL lines from a DSH session artifact (zstd or plain)."""
    raw = path.read_bytes()
    if raw.startswith(_ZSTD_MAGIC):
        # DSH frames carry no content-size header; stream_reader handles them.
        with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)) as reader:
            return reader.read().decode("utf-8").splitlines()
    return raw.decode("utf-8").splitlines()


def _dsh_parse_tool_arguments(raw_arguments: object) -> JsonValue | None:
    """Parse DSH tool-call arguments — a dict payload or a JSON string."""
    if isinstance(raw_arguments, str):
        try:
            return cast(JsonValue, json.loads(raw_arguments))
        except ValueError:
            return None
    if isinstance(raw_arguments, dict):
        return cast(JsonValue, raw_arguments)
    return None


def _normalize_dsh_message(message: object) -> JsonDict | None:
    """Map DSH message content blocks (tool-call) to the shared vocabulary.

    DSH persists ``tool-call`` blocks with ``arguments`` as a JSON string, unlike
    the ``pre_tool_use``/``input`` dict shape the other agent CLIs produce. Both the
    inline ``assistant/message`` blocks here and the ``tool/call`` events (via
    ``_dsh_tool_call_entry``) normalize through one parser so the projector and
    tool-call extractor see the shared ``pre_tool_use`` vocabulary.
    """
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, list):
        return message
    blocks: list[JsonValue] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool-call":
            blocks.append(
                {
                    "type": "pre_tool_use",
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "input": _dsh_parse_tool_arguments(block.get("arguments")),
                }
            )
        else:
            blocks.append(cast(JsonValue, block))
    return {**message, "content": blocks}


def _dsh_tool_call_entry(data: Mapping[str, object], *, timestamp: str | None) -> JsonDict:
    """tool/call event -> pre_tool_use entry (its arguments is a JSON string)."""
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "pre_tool_use",
                    "id": cast(JsonValue | None, data.get("callId")),
                    "name": cast(JsonValue | None, data.get("name")),
                    "input": _dsh_parse_tool_arguments(data.get("arguments")),
                }
            ],
        },
        "timestamp": timestamp,
    }


def _dsh_tool_result_entry(data: Mapping[str, object], *, timestamp: str | None) -> JsonDict | None:
    """tool/result event -> tool_result entry, or None without tool content."""
    message = data.get("message")
    if not isinstance(message, dict):
        return None
    content: list[JsonValue] = []
    for block in message.get("content") if isinstance(message.get("content"), list) else []:
        if isinstance(block, dict) and block.get("type") == "tool-result":
            content.append(
                {
                    "type": "tool_result",
                    "toolCallId": cast(JsonValue | None, block.get("toolCallId")),
                    "content": cast(JsonValue | None, block.get("content")),
                    "is_error": False,
                }
            )
    if not content:
        return None
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": content},
        "timestamp": timestamp,
    }


def _read_claude(path: Path, tail_entries: int | None) -> Iterable[JsonDict]:
    return _iter_claude_entries(path, tail_entries=tail_entries)


def _read_codex(path: Path, tail_entries: int | None) -> Iterable[JsonDict]:
    return _iter_codex_entries(path, tail_entries=tail_entries)


def _read_gemini(path: Path, _tail_entries: int | None) -> Iterable[JsonDict]:
    return _iter_gemini_entries(path)


def _read_deepseek(path: Path, _tail_entries: int | None) -> Iterable[JsonDict]:
    return _iter_deepseek_entries(path)


def _claude_checkpoint_window(entries: Sequence[JsonDict]) -> list[JsonDict]:
    return list(entries)


def _codex_checkpoint_window(entries: Sequence[JsonDict]) -> list[JsonDict]:
    return list(_normalize_codex_entries(entries))


def _native_records(records: Iterable[JsonDict]) -> Iterable[JsonDict]:
    """Keep native Claude entries without a second representation."""
    return records


def _document_record(document: JsonValue) -> Iterable[JsonDict]:
    """Expose a single native JSON object to a record normalizer."""
    return (document,) if isinstance(document, dict) else ()


def _gemini_document_records(document: JsonValue) -> Iterable[JsonDict]:
    """Select the existing legacy Gemini document's message collection."""
    return _coerce_dict_list(document.get(_GEMINI_MESSAGES_FIELD)) if isinstance(document, dict) else ()


def _codex_append_anchor(entry: JsonDict) -> bool:
    """Retain the significant record a subsequent abort can reinterpret."""
    return entry.get(_CODEX_RECORD_TYPE_FIELD) != _CODEX_SESSION_META_TYPE


@dataclass(frozen=True)
class TranscriptReader:
    """How one runtime's native transcript is read and presented.

    ``checkpoint_window`` normalizes a raw JSONL suffix window for runtimes
    whose transcripts can be read from their tail; a runtime without one is
    always read whole. ``turn_completion`` reads the raw tail as the time the
    latest turn ended; a runtime without one has no native completion evidence.
    """

    display_name: str
    read: Callable[[Path, int | None], Iterable[JsonDict]]
    tail_limit: Callable[[str, int], str]
    checkpoint_window: Callable[[Sequence[JsonDict]], list[JsonDict]] | None
    normalize: Callable[[Iterable[JsonDict]], Iterable[JsonDict]]
    document_records: Callable[[JsonValue], Iterable[JsonDict]] = _document_record
    append_anchor: Callable[[JsonDict], bool] | None = None
    format_mismatch_agent: str | None = None
    turn_completion: Callable[[Sequence[JsonDict]], datetime | None] | None = None


TRANSCRIPT_READERS: Mapping[AgentName, TranscriptReader] = MappingProxyType(
    {
        AgentName.CLAUDE: TranscriptReader(
            "Claude Code",
            _read_claude,
            _apply_tail_limit,
            _claude_checkpoint_window,
            _native_records,
            turn_completion=claude_turn_completion,
        ),
        AgentName.CODEX: TranscriptReader(
            "Codex",
            _read_codex,
            _apply_tail_limit_codex,
            _codex_checkpoint_window,
            _normalize_codex_entries,
            append_anchor=_codex_append_anchor,
            turn_completion=codex_turn_completion,
        ),
        AgentName.GEMINI: TranscriptReader(
            "Gemini",
            _read_gemini,
            _apply_tail_limit,
            None,
            _normalize_gemini_entries,
            _gemini_document_records,
            format_mismatch_agent="gemini",
        ),
        AgentName.DEEPSEEK: TranscriptReader(
            "DeepSeek Harness", _read_deepseek, _apply_tail_limit, None, _normalize_deepseek_entries
        ),
    }
)
"""The one reader per runtime; onboarding a harness adds its record here."""


def _cached_entries(path: Path, agent_name: AgentName) -> list[JsonDict] | None:
    """Read through the shared source-view owner using this runtime's codec."""
    return read_transcript_entries(path, agent_name, TRANSCRIPT_READERS[agent_name], _report_transcript_format_mismatch)


def _get_entries_for_agent(
    transcript_path: str,
    agent_name: AgentName,
    *,
    tail_entries: int | None = None,
) -> list[JsonDict] | None:
    """Load and return transcript entries for the given agent type.

    Returns None if the path doesn't exist.
    """
    path = Path(transcript_path).expanduser()
    if tail_entries is not None:
        if not path.exists():
            return None
        return list(TRANSCRIPT_READERS[agent_name].read(path, tail_entries))
    return _cached_entries(path, agent_name)


def read_turn_completion(transcript: SessionTranscript) -> datetime | None:
    """Return when the bound transcript's latest turn ended, or ``None`` without native evidence."""
    turn_completion = TRANSCRIPT_READERS[transcript.agent].turn_completion
    if turn_completion is None:
        return None
    entries = _get_entries_for_agent(transcript.path, transcript.agent, tail_entries=TURN_COMPLETION_TAIL_ENTRIES)
    return turn_completion(entries) if entries else None


def _get_checkpoint_entries_for_agent(transcript_path: str, agent_name: AgentName) -> list[JsonDict] | None:
    """Load the shortest complete JSONL suffix that establishes a checkpoint boundary."""
    checkpoint_window = TRANSCRIPT_READERS[agent_name].checkpoint_window
    if checkpoint_window is None:
        return _get_entries_for_agent(transcript_path, agent_name)

    path = Path(transcript_path).expanduser()
    if not path.exists():
        return None

    for window in _iter_jsonl_entry_windows(path):
        entries = checkpoint_window(window.entries)
        if window.at_beginning or (
            find_last_checkpoint_anchor(entries, agent_name) is not None
            or find_last_turn_start(entries, agent_name) is not None
        ):
            return entries
    return []
