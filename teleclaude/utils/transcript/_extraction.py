"""Transcript extraction: retrieve messages, parse sessions, extract working directories."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from teleclaude.core.agents import AgentName
from teleclaude.core.models import JsonDict

from ._iterators import (
    _get_entries_for_agent,
    _iter_claude_entries,
    _iter_codex_entries,
    _iter_gemini_entries,
    _start_index_after_timestamp_or_rotation,
)
from ._parsers import normalize_transcript_entry_message
from ._rendering import _render_transcript_from_entries
from ._user_turns import (
    extract_real_user_text_from_entry,
    extract_text_from_message_content,
    find_last_real_user_turn,
    find_turn_start_idx,
)
from ._utils import _apply_tail_limit, _apply_tail_limit_codex, _escape_triple_backticks, _parse_timestamp


def get_assistant_messages_since(
    transcript_path: str,
    agent_name: AgentName,
    since_timestamp: datetime | None = None,
) -> list[dict[str, object]]:  # guard: loose-dict - External transcript messages
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

    assistant_messages = []
    for entry in entries[start_idx:]:
        msg = normalize_transcript_entry_message(entry)
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            assistant_messages.append(msg)

    return assistant_messages


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
            elif block_type == "tool_use" and include_tools:
                block_count += 1
            elif block_type == "tool_result" and include_tool_results:
                block_count += 1
    return block_count


def _extract_text_from_content(content: object, role: str) -> str | None:
    """Extract text from message content based on role.

    User-turn filtering needs the full transcript entry and agent-specific
    envelope. Call ``extract_real_user_text_from_entry`` for user messages
    when turn semantics matter.
    """
    return extract_text_from_message_content(content, role)


def _extract_last_message_by_role(
    transcript_path: str,
    agent_name: AgentName,
    target_role: str,
    count: int = 1,
) -> str | None:
    """Extract the last N messages with the specified role from the transcript.

    guard: allow-string-compare

    Args:
        transcript_path: Path to transcript file
        agent_name: Agent type for entry iterator selection
        target_role: Role to search for ("user" or "assistant")
        count: Number of messages to extract (default 1)

    Returns:
        Concatenated text of last N messages, or None if not found
    """
    try:
        entries = _get_entries_for_agent(transcript_path, agent_name)
        if entries is None:
            return None

        collected: list[str] = []
        for entry in reversed(entries):
            message = normalize_transcript_entry_message(entry)

            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if not isinstance(role, str) or role != target_role:
                continue
            if target_role == "user":
                text = extract_real_user_text_from_entry(entry, agent_name)
            else:
                text = _extract_text_from_content(message.get("content"), target_role)
            if text is not None:
                collected.append(text)
                if len(collected) >= count:
                    break

        if not collected:
            return None
        # Reverse to get chronological order
        collected.reverse()
        return "\n\n".join(collected)
    except Exception:
        return None


def extract_last_user_message(
    transcript_path: str,
    agent_name: AgentName,
) -> str | None:
    """Extract the last user message from the transcript.

    Args:
        transcript_path: Path to transcript file
        agent_name: Agent type for entry iterator selection

    Returns:
        Last user message text or None if not found
    """
    return _extract_last_message_by_role(transcript_path, agent_name, "user")


def extract_last_user_message_with_timestamp(
    transcript_path: str,
    agent_name: AgentName,
) -> tuple[str, datetime | None] | None:
    """Extract the last user message and its transcript timestamp.

    Returns:
        Tuple of (message text, parsed timestamp) when found, otherwise None.
    """
    try:
        entries = _get_entries_for_agent(transcript_path, agent_name)
        if entries is None:
            return None

        for entry in reversed(entries):
            text = extract_real_user_text_from_entry(entry, agent_name)
            if text is None:
                continue

            entry_ts = entry.get("timestamp")
            parsed_ts = _parse_timestamp(entry_ts) if isinstance(entry_ts, str) else None
            return text, parsed_ts
    except Exception:
        return None

    return None


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

    turn = find_last_real_user_turn(entries, agent_name)
    return turn.timestamp if turn is not None else None


def extract_last_agent_message(
    transcript_path: str,
    agent_name: AgentName,
    count: int = 1,
) -> str | None:
    """Extract the last N assistant/agent text messages from the transcript.

    Only extracts actual text content, skipping tool_use and thinking blocks.

    Args:
        transcript_path: Path to transcript file
        agent_name: Agent type for entry iterator selection
        count: Number of messages to extract (default 1)

    Returns:
        Concatenated text of last N assistant messages, or None if not found
    """
    return _extract_last_message_by_role(transcript_path, agent_name, "assistant", count)


def collect_transcript_messages(
    transcript_path: str,
    agent_name: AgentName,
) -> list[tuple[str, str]]:
    """Collect (role, text) message pairs from a transcript."""
    entries = _get_entries_for_agent(transcript_path, agent_name)
    if entries is None:
        return []

    messages: list[tuple[str, str]] = []
    for entry in entries:
        message = normalize_transcript_entry_message(entry)
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if not isinstance(role, str):
            continue
        if role == "user":
            text = extract_real_user_text_from_entry(entry, agent_name)
        else:
            text = _extract_text_from_content(message.get("content"), role)
        if text:
            messages.append((role, text))
    return messages


def extract_recent_transcript_turns(
    transcript_path: str,
    agent_name: AgentName,
    *,
    max_turns_per_role: int = 3,
) -> list[tuple[str, str]]:
    """Return the most recent interleaved user/assistant transcript turns.

    Uses the shared transcript normalization pipeline and keeps messages in their
    original order while limiting each side to the most recent N turns.
    """
    if max_turns_per_role <= 0:
        return []

    messages = collect_transcript_messages(transcript_path, agent_name)
    if not messages:
        return []

    selected_reversed: list[tuple[str, str]] = []
    counts = {"user": 0, "assistant": 0}
    for role, text in reversed(messages):
        if role not in counts:
            continue
        if counts[role] >= max_turns_per_role:
            continue
        selected_reversed.append((role, text))
        counts[role] += 1
        if all(count >= max_turns_per_role for count in counts.values()):
            break

    return list(reversed(selected_reversed))


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

    iterators: dict[AgentName, Callable[..., Iterable[JsonDict]]] = {
        AgentName.CLAUDE: _iter_claude_entries,
        AgentName.GEMINI: _iter_gemini_entries,
        AgentName.CODEX: _iter_codex_entries,
    }
    iter_fn = iterators.get(agent_name)
    if not iter_fn:
        return f"Unknown agent: {agent_name}"

    tail_fn = _apply_tail_limit_codex if agent_name == AgentName.CODEX else _apply_tail_limit
    rendered = _render_transcript_from_entries(
        iter_fn(path),  # type: ignore[arg-type]
        title,
        since_timestamp,
        until_timestamp,
        tail_chars,
        tail_limit_fn=tail_fn,
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
