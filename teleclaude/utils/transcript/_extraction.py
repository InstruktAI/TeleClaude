"""Transcript extraction: retrieve messages, parse sessions, extract working directories."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from teleclaude.core.agents import AgentName
from teleclaude.core.models import JsonDict
from teleclaude.core.session_output import (
    NOOP_SENTINEL,
    StopOutputKind,
    StopOutputResult,
    classify_stop_output,
    is_bare_noop_output,
)

from ._identity import native_entry_id
from ._iterators import (
    TRANSCRIPT_READERS,
    _get_entries_for_agent,
    _start_index_after_timestamp_or_rotation,
    collect_transcript_format_mismatches,
)
from ._parsers import normalize_transcript_entry_message
from ._rendering import render_transcript_from_entries
from ._user_turns import (
    extract_authored_user_text,
    extract_text_from_message_content,
    find_last_turn_start,
    find_turn_start_idx,
    is_response_start_entry,
)
from ._utils import (
    _escape_triple_backticks,
    _parse_timestamp,
)

_MESSAGE_ROLE_FIELD = "role"
_MESSAGE_CONTENT_FIELD = "content"
_ENTRY_TIMESTAMP_FIELD = "timestamp"
_ASSISTANT_ROLE = "assistant"


def _assistant_messages(entries: Sequence[JsonDict]) -> list[JsonDict]:
    """Return the normalized assistant messages among transcript entries, in order."""
    messages: list[JsonDict] = []
    for entry in entries:
        message = normalize_transcript_entry_message(entry)
        if isinstance(message, dict) and message.get(_MESSAGE_ROLE_FIELD) == _ASSISTANT_ROLE:
            messages.append(cast(JsonDict, message))
    return messages


def get_assistant_messages_since(
    transcript_path: str,
    agent_name: AgentName,
    since_timestamp: datetime | None = None,
) -> list[JsonDict]:
    """Retrieve assistant message objects from transcript since a timestamp.

    Args:
        transcript_path: Path to transcript file
        agent_name: Agent name for iterator selection
        since_timestamp: Optional UTC datetime boundary.

    Returns:
        List of assistant message objects (with role and content).
    """
    entries = _get_entries_for_agent(transcript_path, agent_name)
    if not entries:
        return []

    # Find activity AFTER since_timestamp
    start_idx = 0
    if since_timestamp:
        start_idx = _start_index_after_timestamp_or_rotation(
            entries,
            since_timestamp,
            transcript_path=transcript_path,
            agent_name=agent_name,
            mode="messages",
        )
        if start_idx is None:
            return []
    else:
        start_idx = find_turn_start_idx(entries, full_session=False, agent_name=agent_name)

    return _assistant_messages(entries[start_idx:])


def count_renderable_assistant_blocks(
    transcript_path: str,
    agent_name: AgentName,
    since_timestamp: datetime | None = None,
    *,
    include_tools: bool = False,
    include_tool_results: bool = False,
) -> int:
    """Count assistant content blocks renderable by incremental output."""
    assistant_messages = get_assistant_messages_since(
        transcript_path,
        agent_name,
        since_timestamp=since_timestamp,
    )
    block_count = 0
    for message in assistant_messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type in ("text", "output_text", "thinking"):
                block_count += 1
            elif block_type == "pre_tool_use" and include_tools:
                block_count += 1
            elif block_type == "tool_result" and include_tool_results:
                block_count += 1
    return block_count


@dataclass(frozen=True)
class AuthoredExchange:
    """The last authored input in a transcript and the assistant text that followed it."""

    authored_text: str
    timestamp: datetime | None
    assistant_texts: tuple[str, ...]


def _last_authored_entry(entries: Sequence[JsonDict], agent_name: AgentName) -> tuple[int, str] | None:
    """Return the position and text of the last entry carrying authored input."""
    for index in range(len(entries) - 1, -1, -1):
        text = extract_authored_user_text(entries[index], agent_name)
        if text is not None:
            return index, text
    return None


def _entry_time(entry: JsonDict) -> datetime | None:
    raw = entry.get(_ENTRY_TIMESTAMP_FIELD)
    return _parse_timestamp(raw) if isinstance(raw, str) else None


def extract_last_user_message_with_timestamp(
    transcript_path: str,
    agent_name: AgentName,
) -> tuple[str, datetime | None] | None:
    """Extract the last authored input and its transcript timestamp."""
    try:
        entries = _get_entries_for_agent(transcript_path, agent_name)
    except OSError:
        return None
    found = _last_authored_entry(entries, agent_name) if entries else None
    if found is None:
        return None
    index, text = found
    return text, _entry_time(entries[index])


def extract_last_authored_exchange(transcript_path: str, agent_name: AgentName) -> AuthoredExchange | None:
    """Extract the last authored input and the non-empty assistant text written after it."""
    try:
        entries = _get_entries_for_agent(transcript_path, agent_name)
    except OSError:
        return None
    found = _last_authored_entry(entries, agent_name) if entries else None
    if found is None:
        return None
    index, text = found
    assistant_texts = tuple(
        reply
        for message in _assistant_messages(entries[index + 1 :])
        if (reply := extract_text_from_message_content(message.get(_MESSAGE_CONTENT_FIELD), _ASSISTANT_ROLE))
        and reply.strip()
    )
    return AuthoredExchange(authored_text=text, timestamp=_entry_time(entries[index]), assistant_texts=assistant_texts)


def extract_last_turn_boundary_timestamp(
    transcript_path: str,
    agent_name: AgentName,
) -> datetime | None:
    """Return the timestamp of the last genuine user message in the transcript.

    A "genuine" user message is a real human turn — not an agent-generated
    tool_result message. The returned timestamp identifies the start of the
    current assistant turn and is the anchor used by output delivery to
    detect turn boundaries between two cadence ticks.

    Returns:
        The parsed timestamp, or None if the transcript is unreadable,
        empty, contains no genuine user messages, or the latest genuine user
        message has no parseable timestamp.
    """
    try:
        entries = _get_entries_for_agent(transcript_path, agent_name)
    except Exception:
        return None
    if not entries:
        return None

    turn = find_last_turn_start(entries, agent_name)
    return turn.timestamp if turn is not None else None


def _observed_assistant_text(message: Mapping[str, object]) -> tuple[bool, str | None]:
    """Return whether one normalized assistant message explicitly carries text."""
    content = message.get("content")
    if isinstance(content, str):
        return True, content
    if not isinstance(content, list):
        return False, None

    chunks: list[str] = []
    observed = False
    for block in content:
        if not isinstance(block, Mapping) or block.get("type") not in {"text", "output_text"}:
            continue
        text = block.get("text")
        if isinstance(text, str):
            observed = True
            chunks.append(text)
    return observed, "\n\n".join(chunks) if observed else None


def _response_assistant_messages(
    entries: list[JsonDict], agent_name: AgentName, response_entry_id: str | None = None
) -> tuple[str | None, list[JsonDict]] | None:
    """Read one native response, bounded by submitted inputs rather than conversation generations."""
    for index in range(len(entries) - 1, -1, -1):
        entry = entries[index]
        if not is_response_start_entry(entry, agent_name):
            continue
        entry_id = native_entry_id(entry, agent_name)
        if response_entry_id is not None and entry_id != response_entry_id:
            continue
        end = index + 1
        while end < len(entries) and not is_response_start_entry(entries[end], agent_name):
            end += 1
        return entry_id, _assistant_messages(entries[index + 1 : end])
    return None


def _extract_observed_stop_text(messages: Iterable[Mapping[str, object]]) -> tuple[bool, str | None]:
    """Return whether the response carries text, retaining an observed empty value."""
    chunks: list[str] = []
    response_observed = False
    sentinel_seen = False
    for message in messages:
        observed, text = _observed_assistant_text(message)
        if observed:
            response_observed = True
            if text is not None:
                if is_bare_noop_output(text):
                    sentinel_seen = True
                elif text.strip():
                    chunks.append(text)
    if not response_observed:
        return False, None
    if chunks:
        return True, "\n\n".join(chunks)
    return True, NOOP_SENTINEL if sentinel_seen else ""


def extract_stop_agent_output(
    transcript_path: str, agent_name: AgentName, *, response_entry_id: str | None = None
) -> StopOutputResult:
    """Collect authored response text and retain the native identity for delayed reads."""
    try:
        entries = _get_entries_for_agent(transcript_path, agent_name)
    except OSError:
        return StopOutputResult(StopOutputKind.UNAVAILABLE, response_entry_id=response_entry_id)
    if not entries:
        return StopOutputResult(StopOutputKind.UNAVAILABLE, response_entry_id=response_entry_id)
    response = _response_assistant_messages(entries, agent_name, response_entry_id)
    if response is None:
        return StopOutputResult(StopOutputKind.UNAVAILABLE, response_entry_id=response_entry_id)
    entry_id, messages = response
    observed, text = _extract_observed_stop_text(messages)
    if not observed or text is None:
        return StopOutputResult(StopOutputKind.UNAVAILABLE, response_entry_id=entry_id)
    classified = classify_stop_output(text)
    return StopOutputResult(classified.kind, classified.raw_output, entry_id)


def transcript_has_stop_response(
    entries: list[JsonDict], agent_name: AgentName, *, response_entry_id: str | None = None
) -> bool:
    """Return whether the current turn has an explicitly observed text response."""
    response = _response_assistant_messages(entries, agent_name, response_entry_id)
    if response is None:
        return False
    observed, _text = _extract_observed_stop_text(response[1])
    return observed


def parse_session_transcript(
    transcript_path: str,
    title: str,
    *,
    agent_name: AgentName,
    since_timestamp: str | None = None,
    until_timestamp: str | None = None,
    tail_chars: int = 2000,
    escape_triple_backticks: bool = False,
    collapse_tool_results: bool = False,
    include_thinking: bool = True,
    include_tools: bool = True,
    on_format_mismatch: Callable[[str, Path, json.JSONDecodeError], None] | None = None,
) -> str:
    """Parse a session transcript using the agent-specific parser.

    Args:
        transcript_path: Path to transcript file
        title: Session title for header
        agent_name: Agent type for parser selection
        since_timestamp: Optional ISO 8601 UTC start filter (inclusive)
        until_timestamp: Optional ISO 8601 UTC end filter (inclusive)
        tail_chars: Max characters to return from end (default 2000, 0 for unlimited)
        escape_triple_backticks: If True, escape ``` to avoid breaking outer code blocks
        include_thinking: Include thinking blocks (default True)
        include_tools: Include tool calls and results (default True)
    """
    path = Path(transcript_path).expanduser()
    if not path.exists():
        return f"Transcript file not found: {transcript_path}"

    reader = TRANSCRIPT_READERS[agent_name]
    with collect_transcript_format_mismatches(on_format_mismatch):
        rendered = render_transcript_from_entries(
            reader.read(path, None),  # type: ignore[arg-type]
            title,
            since_timestamp,
            until_timestamp,
            tail_chars,
            tail_limit_fn=reader.tail_limit,
            collapse_tool_results=collapse_tool_results,
            include_thinking=include_thinking,
            include_tools=include_tools,
        )
    if escape_triple_backticks:
        return _escape_triple_backticks(rendered)
    return rendered


_WORKDIR_KEYS = {
    "cwd",
    "working_dir",
    "workdir",
    "workingDirectory",
    "workspace",
    "workspaceRoot",
    "project_path",
    "projectRoot",
    "root",
    "root_dir",
    "rootPath",
}


def _find_workdir_in_obj(obj: object) -> str | None:
    """Recursively search for a working directory string in a JSON object."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in _WORKDIR_KEYS and isinstance(value, str):
                candidate = value.strip()
                if candidate and Path(candidate).is_absolute():
                    return candidate
            found = _find_workdir_in_obj(value)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_workdir_in_obj(item)
            if found:
                return found
    return None


def _collect_abs_paths(obj: object, out: list[str]) -> None:
    """Collect absolute filesystem paths from a nested JSON object."""
    if isinstance(obj, dict):
        for value in obj.values():
            _collect_abs_paths(value, out)
        return
    if isinstance(obj, list):
        for item in obj:
            _collect_abs_paths(item, out)
        return
    if isinstance(obj, str) and Path(obj).is_absolute():
        out.append(obj.strip())


def _derive_workdir_from_paths(paths: list[str]) -> str | None:
    """Infer a common workdir from absolute file or directory paths."""
    normalized: list[str] = []
    for raw in paths:
        candidate = raw.strip()
        if not candidate:
            continue
        path = Path(candidate)
        if path.suffix and not candidate.endswith("/"):
            path = path.parent
        normalized.append(str(path))

    if not normalized:
        return None

    try:
        common = Path(os.path.commonpath(normalized))
    except ValueError:
        return normalized[0]

    if common.is_file():
        common = common.parent
    return str(common)


def _extract_workdir_from_jsonl(path: Path) -> str | None:
    """Inspect a JSONL transcript for explicit or inferred workdir metadata."""
    abs_paths: list[str] = []
    with open(path, encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if idx > 200:
                break
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(entry, dict) and entry.get("type") == "session_meta":
                found = _find_workdir_in_obj(entry.get("payload"))
                if found:
                    return found

            _collect_abs_paths(entry, abs_paths)
            found = _find_workdir_in_obj(entry)
            if found:
                return found

    return _derive_workdir_from_paths(abs_paths)


def _extract_workdir_from_json(path: Path) -> str | None:
    """Inspect a JSON transcript for explicit or inferred workdir metadata."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    found = _find_workdir_in_obj(data)
    if found:
        return found

    abs_paths: list[str] = []
    _collect_abs_paths(data, abs_paths)
    return _derive_workdir_from_paths(abs_paths)


def extract_workdir_from_transcript(transcript_path: str) -> str | None:
    """Extract a working directory path from a native transcript file."""
    path = Path(transcript_path).expanduser()
    if not path.exists():
        return None

    try:
        if path.suffix == ".jsonl":
            return _extract_workdir_from_jsonl(path)

        if path.suffix == ".json":
            return _extract_workdir_from_json(path)
    except OSError:
        return None
    except json.JSONDecodeError:
        return None

    return None
