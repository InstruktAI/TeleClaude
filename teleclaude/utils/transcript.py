"""Parse and convert Claude/Gemini/Codex session transcripts to markdown."""

import json
import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, cast

from teleclaude.core.agents import AgentName
from teleclaude.core.dates import format_local_datetime

logger = logging.getLogger(__name__)


def parse_claude_transcript(
    transcript_path: str,
    title: str,
    since_timestamp: Optional[str] = None,
    until_timestamp: Optional[str] = None,
    tail_chars: int = 2000,
    collapse_tool_results: bool = False,
) -> str:
    """Convert Claude Code JSONL transcript to markdown with filtering.

    guard: allow-string-compare

    Args:
        transcript_path: Path to Claude session .jsonl file
        title: Session title for header
        since_timestamp: Optional ISO 8601 UTC start filter (inclusive)
        until_timestamp: Optional ISO 8601 UTC end filter (inclusive)
        tail_chars: Max characters to return from end (default 2000, 0 for unlimited)

    Returns:
        Markdown formatted conversation with timestamps on each section
    """
    path = Path(transcript_path).expanduser()
    if not path.exists():
        return f"Transcript file not found: {transcript_path}"

    try:
        entries = _iter_claude_entries(path)
        return _render_transcript_from_entries(
            entries,
            title,
            since_timestamp,
            until_timestamp,
            tail_chars,
            collapse_tool_results=collapse_tool_results,
        )
    except Exception as e:
        return f"Error parsing transcript: {e}"


def parse_codex_transcript(
    transcript_path: str,
    title: str,
    since_timestamp: Optional[str] = None,
    until_timestamp: Optional[str] = None,
    tail_chars: int = 2000,
    collapse_tool_results: bool = False,
) -> str:
    """Convert Codex JSONL transcript to markdown with filtering.

    guard: allow-string-compare
    """

    path = Path(transcript_path).expanduser()
    if not path.exists():
        return f"Transcript file not found: {transcript_path}"

    try:
        entries = _iter_codex_entries(path)
        return _render_transcript_from_entries(
            entries,
            title,
            since_timestamp,
            until_timestamp,
            tail_chars,
            tail_limit_fn=_apply_tail_limit_codex,
            collapse_tool_results=collapse_tool_results,
        )
    except Exception as e:
        return f"Error parsing transcript: {e}"


def parse_gemini_transcript(
    transcript_path: str,
    title: str,
    since_timestamp: Optional[str] = None,
    until_timestamp: Optional[str] = None,
    tail_chars: int = 2000,
    collapse_tool_results: bool = False,
) -> str:
    """Convert Gemini JSON transcript into markdown.

    guard: allow-string-compare
    """

    path = Path(transcript_path).expanduser()
    if not path.exists():
        return f"Transcript file not found: {transcript_path}"

    try:
        entries = _iter_gemini_entries(path)
        return _render_transcript_from_entries(
            entries,
            title,
            since_timestamp,
            until_timestamp,
            tail_chars,
            collapse_tool_results=collapse_tool_results,
        )
    except Exception as e:
        return f"Error parsing transcript: {e}"


def _should_skip_entry(
    entry: dict[str, object],  # guard: loose-dict - External entry
    since_dt: Optional[datetime],
    until_dt: Optional[datetime],
) -> bool:
    """Check if entry should be skipped based on type and timestamp filters.

    guard: allow-string-compare
    """
    if entry.get("type") == "summary":
        return True

    entry_timestamp = entry.get("timestamp")
    if isinstance(entry_timestamp, str):
        entry_dt = _parse_timestamp(entry_timestamp)
        if since_dt and entry_dt and entry_dt < since_dt:
            return True
        if until_dt and entry_dt and entry_dt > until_dt:
            return True
        if (since_dt or until_dt) and entry_dt is None:
            return True
    elif since_dt or until_dt:
        return True

    return False


def _process_entry(
    entry: dict[str, object],  # guard: loose-dict - External entry
    lines: list[str],
    last_section: Optional[str],
    collapse_tool_results: bool,
) -> Optional[str]:  # guard: loose-dict - External entry
    """Process a transcript entry and append formatted content to lines.

    guard: allow-string-compare
    """
    entry_timestamp = entry.get("timestamp")
    entry_dt = None
    if isinstance(entry_timestamp, str):
        entry_dt = _parse_timestamp(entry_timestamp)
    time_prefix = _format_timestamp_prefix(entry_dt) if entry_dt else ""

    message = entry.get("message")

    # Handle Codex/Gemini "response_item" format where message is in payload
    if not isinstance(message, dict) and entry.get("type") == "response_item":
        payload = entry.get("payload")
        if isinstance(payload, dict):
            message = payload

    if not isinstance(message, dict):
        return last_section

    role = message.get("role")
    content: object = message.get("content", [])

    if not role or not isinstance(role, str):
        return last_section

    if isinstance(content, str):
        return _process_string_content(content, time_prefix, lines, last_section)

    if isinstance(content, list):
        return _process_list_content(content, role, time_prefix, lines, last_section, collapse_tool_results)

    return last_section


def _process_string_content(content: str, time_prefix: str, lines: list[str], last_section: Optional[str]) -> str:
    """Process string content (user message).

    guard: allow-string-compare
    """
    if last_section != "user" or time_prefix:
        lines.append("")
        lines.append(f"## {time_prefix}👤 User")
        lines.append("")
    lines.append(content)
    return "user"


def _process_list_content(
    content: list[object],
    role: str,
    time_prefix: str,
    lines: list[str],
    last_section: Optional[str],
    collapse_tool_results: bool,
) -> Optional[str]:
    """Process list of content blocks.

    guard: allow-string-compare
    """
    current_section = last_section

    for block in content:
        if not isinstance(block, dict):
            continue

        block_type = block.get("type")
        if not isinstance(block_type, str):
            continue

        if block_type in ("text", "input_text", "output_text"):
            current_section = _process_text_block(block, role, time_prefix, lines, current_section)
        elif block_type == "thinking":
            current_section = _process_thinking_block(block, time_prefix, lines, current_section)
        elif block_type == "tool_use":
            current_section = _process_tool_use_block(block, time_prefix, lines)
        elif block_type == "tool_result":
            current_section = _process_tool_result_block(
                block,
                time_prefix,
                lines,
                collapse_tool_results,
            )

    return current_section


def _process_text_block(
    block: dict[str, object],  # guard: loose-dict - External block
    role: str,
    time_prefix: str,
    lines: list[str],
    last_section: Optional[str],
) -> Optional[str]:
    """Process text block from assistant or user.

    guard: allow-string-compare
    """
    if role == "assistant" and last_section != "assistant":
        lines.append("")
        lines.append(f"## {time_prefix}🤖 Assistant")
        lines.append("")
    elif role == "user" and (last_section != "user" or time_prefix):
        lines.append("")
        lines.append(f"## {time_prefix}👤 User")
        lines.append("")

    text = block.get("text", "")
    lines.append(str(text))

    if role == "assistant":
        return "assistant"
    if role == "user":
        return "user"
    return last_section


def _process_thinking_block(
    block: dict[str, object],  # guard: loose-dict - External block
    time_prefix: str,
    lines: list[str],
    last_section: Optional[str],
) -> str:
    """Process thinking block.

    guard: allow-string-compare
    """
    if last_section != "assistant":
        lines.append("")
        lines.append(f"## {time_prefix}🤖 Assistant")
        lines.append("")
    thinking = block.get("thinking", "")
    formatted_thinking = _format_thinking(str(thinking))
    lines.append(formatted_thinking)
    return "assistant"


def _process_tool_use_block(
    block: dict[str, object],  # guard: loose-dict - External block
    time_prefix: str,
    lines: list[str],
) -> str:
    """Process tool use block.

    guard: allow-string-compare
    """
    tool_name = block.get("name", "unknown")
    tool_input = block.get("input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}
    serialized_input = json.dumps(tool_input)
    lines.append("")
    # Use bold single-backtick monospace for tool invocations
    lines.append(f"{time_prefix}🔧 **`{tool_name} {serialized_input}`**")
    return "tool_use"


def render_clean_agent_output(
    transcript_path: str,
    agent_name: AgentName,
    since_timestamp: Optional[datetime] = None,
) -> tuple[Optional[str], Optional[datetime]]:
    """Render metadata-free markdown for assistant activity.

    Used for sequential, incremental output blocks in the UI.
    Renders thinking in italics and tool invocations in bold monospace.
    Completely omits tool results.

    Args:
        transcript_path: Path to transcript file
        agent_name: Agent name for iterator selection
        since_timestamp: Optional UTC datetime boundary.

    Returns:
        Tuple of (markdown text or None, timestamp of last rendered entry or None)
    """
    entries = _get_entries_for_agent(transcript_path, agent_name)
    if not entries:
        return None, None

    # Find the lower boundary (activity after since_timestamp)
    start_idx = 0
    if since_timestamp:
        if since_timestamp.tzinfo is None:
            since_timestamp = since_timestamp.replace(tzinfo=timezone.utc)

        for i, entry in enumerate(entries):
            entry_ts_str = entry.get("timestamp")
            if isinstance(entry_ts_str, str):
                entry_dt = _parse_timestamp(entry_ts_str)
                if entry_dt:
                    if entry_dt.tzinfo is None:
                        entry_dt = entry_dt.replace(tzinfo=timezone.utc)

                    if entry_dt > since_timestamp:
                        start_idx = i
                        break
        else:
            return None, None
    else:
        # Fall back to last user boundary if no timestamp provided
        last_user_idx = -1
        for i in range(len(entries) - 1, -1, -1):
            entry = entries[i]
            message = entry.get("message") or entry.get("payload")
            if isinstance(message, dict) and message.get("role") == "user":
                last_user_idx = i
                break
        start_idx = last_user_idx + 1

    assistant_entries = entries[start_idx:]
    if not assistant_entries:
        return None, None

    lines: list[str] = []
    emitted = False
    last_entry_dt: Optional[datetime] = None

    for entry in assistant_entries:
        entry_ts_str = entry.get("timestamp")
        if isinstance(entry_ts_str, str):
            last_entry_dt = _parse_timestamp(entry_ts_str)

        message = entry.get("message") or entry.get("payload")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue

        content = message.get("content")
        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")

            if block_type in ("text", "output_text"):
                text = block.get("text", "")
                if text:
                    if lines:
                        lines.append("")
                    lines.append(str(text))
                    emitted = True
            elif block_type == "thinking":
                thinking = block.get("thinking", "")
                if thinking:
                    if lines:
                        lines.append("")
                    # Clean thinking: just italics, no headers
                    lines.append(f"_{thinking}_")
                    emitted = True
            elif block_type == "tool_use":
                tool_name = block.get("name", "unknown")
                tool_input = block.get("input", {})
                serialized = json.dumps(tool_input)
                if lines:
                    lines.append("")
                # Clean tool use: bold single-backtick monospace
                lines.append(f"🔧 **`{tool_name} {serialized}`**")
                emitted = True
            # Tool results are completely omitted in this "clean" renderer

    if not emitted:
        return None, last_entry_dt

    return "\n".join(lines).strip(), last_entry_dt


def _process_tool_result_block(
    block: dict[str, object],  # guard: loose-dict - External block
    time_prefix: str,
    lines: list[str],
    collapse_tool_results: bool,
    max_chars: Optional[int] = None,
) -> str:  # guard: loose-dict - External block
    """Process tool result block.

    guard: allow-string-compare
    """
    is_error = block.get("is_error", False)
    status_emoji = "❌" if is_error else "✅"
    content_data = block.get("content", "")
    content_str = str(content_data)

    if max_chars and len(content_str) > max_chars:
        content_str = content_str[:max_chars] + "\n[...tool output truncated...]"

    lines.append("")
    content_lines = content_str.splitlines() or [""]
    if collapse_tool_results:
        lines.append(f"{time_prefix}{status_emoji} **TOOL RESPONSE (tap to reveal):**")
        lines.append("")
        for line in content_lines:
            lines.append(f"||{line}||" if line else "|| ||")
        lines.append("")
    else:
        lines.append(f"{time_prefix}{status_emoji} **TOOL RESPONSE:**")
        lines.append("")
        for line in content_lines:
            lines.append(f"> {line}" if line else ">")
        lines.append("")
    return "tool_result"


def _apply_tail_limit(result: str, tail_chars: int) -> str:
    """Apply tail_chars limit to result."""
    if 0 < tail_chars < len(result):
        truncated = result[-tail_chars:]
        header_pos = truncated.find("\n## ")
        if 0 <= header_pos < 500:
            truncated = truncated[header_pos + 1 :]
        return f"[...truncated, showing last {tail_chars} chars...]\n\n{truncated}"
    return result


def _apply_tail_limit_codex(result: str, tail_chars: int) -> str:
    """Apply tail_chars limit for Codex transcripts.

    Codex clients can truncate tool output from the start; for long transcripts
    we prefer to start at a recent section boundary that keeps most of the
    newest window while dropping older content.
    """
    if not (0 < tail_chars < len(result)):
        return result

    truncated = result[-tail_chars:]

    # Prefer the first header after a small cutoff so we drop older content
    # but retain most of the recent window.
    header_positions = [i for i in range(len(truncated)) if truncated.startswith("\n## ", i)]
    if header_positions:
        cutoff = min(500, max(0, int(len(truncated) * 0.1)))
        chosen_pos = next((pos for pos in header_positions if pos >= cutoff), header_positions[0])
        truncated = truncated[chosen_pos + 1 :]

    return f"[...truncated, showing last {tail_chars} chars...]\n\n{truncated}"


def _parse_timestamp(ts: str) -> Optional[datetime]:
    """Parse ISO 8601 timestamp string to datetime.

    Args:
        ts: ISO 8601 timestamp (e.g., "2025-11-11T04:25:33.890Z")

    Returns:
        datetime object or None if parsing fails
    """
    if not ts:
        return None
    try:
        # Handle Z suffix and milliseconds
        ts_clean = ts.replace("Z", "+00:00")
        # Try with microseconds first, then without
        for fmt in ["%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"]:
            try:
                parsed = datetime.strptime(ts_clean, fmt)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        # Fallback: fromisoformat handles most cases
        parsed = datetime.fromisoformat(ts_clean)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _format_timestamp_prefix(dt: datetime) -> str:
    """Format datetime as prefix for section headers in local timezone.

    Args:
        dt: datetime object (UTC or timezone-aware)

    Returns:
        Formatted string like "14:25:33 · " or "2025-11-11 14:25:33 · "
    """
    # Convert to local timezone for comparison
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone()
    now = datetime.now().astimezone()

    # If same day, just show time
    if local_dt.date() == now.date():
        return f"{format_local_datetime(dt, include_date=False)} · "

    # Different day, show full date + time
    return f"{format_local_datetime(dt, include_date=True)} · "


def _format_thinking(text: str) -> str:
    """Format thinking block with italics, preserving code blocks.

    Args:
        text: Thinking block text

    Returns:
        Formatted markdown with italics for non-code lines, blank line after
    """
    lines = text.split("\n")
    result_lines = []
    in_code_block = False

    for line in lines:
        if line.strip().startswith("```"):
            if not in_code_block:
                # Add blank line before opening backticks
                result_lines.append("")
            result_lines.append(line)
            in_code_block = not in_code_block
        elif in_code_block or not line.strip():
            result_lines.append(line)
        else:
            result_lines.append(f"*{line}*")

    # Add blank line after thinking block
    result_lines.append("")

    return "\n".join(result_lines)


def _render_transcript_from_entries(
    entries: Iterable[dict[str, object]],  # guard: loose-dict - External entries
    title: str,
    since_timestamp: Optional[str],
    until_timestamp: Optional[str],
    tail_chars: int,
    *,
    tail_limit_fn: Callable[[str, int], str] = _apply_tail_limit,
    collapse_tool_results: bool = False,
) -> str:
    """Render markdown from normalized transcript entries."""

    since_dt = _parse_timestamp(since_timestamp) if since_timestamp else None
    until_dt = _parse_timestamp(until_timestamp) if until_timestamp else None

    lines: list[str] = [f"# {title}", ""]
    last_section: Optional[str] = None
    emitted = False

    for entry in entries:
        if _should_skip_entry(entry, since_dt, until_dt):
            continue

        before_len = len(lines)
        last_section = _process_entry(entry, lines, last_section, collapse_tool_results)
        if len(lines) != before_len:
            emitted = True

    if not emitted and (since_timestamp or until_timestamp):
        lines.append("_No entries in the requested time range._")

    result = "\n".join(lines)
    return tail_limit_fn(result, tail_chars)


def _iter_jsonl_entries(
    path: Path,
) -> Iterable[dict[str, object]]:  # guard: loose-dict - External JSONL unknown structure
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
                yield cast(dict[str, object], entry_value)  # guard: loose-dict - Parsed JSONL entry


def _iter_claude_entries(
    path: Path,
) -> Iterable[dict[str, object]]:  # guard: loose-dict - External JSONL unknown structure
    """Yield entries from Claude Code transcripts (raw JSONL)."""

    yield from _iter_jsonl_entries(path)


def _iter_codex_entries(
    path: Path,
) -> Iterable[dict[str, object]]:  # guard: loose-dict - External JSONL unknown structure
    """Yield entries from Codex JSONL transcripts, skipping metadata.

    guard: allow-string-compare
    """

    for entry in _iter_jsonl_entries(path):
        if entry.get("type") == "session_meta":
            continue
        yield entry


def _iter_gemini_entries(
    path: Path,
) -> Iterable[dict[str, object]]:  # guard: loose-dict - External JSONL unknown structure
    """Yield normalized entries from Gemini JSON session files.

    guard: allow-string-compare
    """

    with open(path, encoding="utf-8") as f:
        raw_document: object = json.load(f)

    document: dict[str, object] = {}  # guard: loose-dict - External JSON document
    if isinstance(raw_document, dict):
        document = cast(dict[str, object], raw_document)  # guard: loose-dict - External JSON document

    raw_messages = document.get("messages", [])
    messages: list[dict[str, object]] = []  # guard: loose-dict - External JSON messages
    if isinstance(raw_messages, list):
        for item in raw_messages:
            if isinstance(item, dict):
                messages.append(cast(dict[str, object], item))  # guard: loose-dict - External JSON message

    for message in messages:
        msg_type = message.get("type")
        timestamp = message.get("timestamp")

        if msg_type == "user":
            content_value = message.get("content", "")
            yield {
                "type": "user",
                "timestamp": timestamp,
                "message": {
                    "role": "user",
                    "content": [{"type": "input_text", "text": str(content_value)}],
                },
            }
            continue

        if msg_type != "gemini":
            continue

        blocks: list[dict[str, object]] = []  # guard: loose-dict - Internal normalized blocks
        thoughts_raw = message.get("thoughts")
        thoughts: list[dict[str, object]] = []  # guard: loose-dict - External thoughts
        if isinstance(thoughts_raw, list):
            for thought_item in thoughts_raw:
                if isinstance(thought_item, dict):
                    thoughts.append(cast(dict[str, object], thought_item))  # guard: loose-dict - External thought

        for thought in thoughts:
            description = thought.get("description") or thought.get("text") or ""
            if description:
                blocks.append({"type": "thinking", "thinking": description})

        content_text = message.get("content")
        if content_text:
            blocks.append({"type": "text", "text": str(content_text)})

        tool_calls_raw = message.get("toolCalls")
        tool_calls: list[dict[str, object]] = []  # guard: loose-dict - External tool calls
        if isinstance(tool_calls_raw, list):
            for tool_item in tool_calls_raw:
                if isinstance(tool_item, dict):
                    tool_calls.append(cast(dict[str, object], tool_item))  # guard: loose-dict - External tool call

        for tool_call in tool_calls:
            name = tool_call.get("displayName") or tool_call.get("name") or "tool"
            args = tool_call.get("args")
            input_payload: dict[str, object] = {}  # guard: loose-dict - External tool args
            if isinstance(args, dict):
                input_payload = cast(dict[str, object], args)  # guard: loose-dict - External tool args
            blocks.append(
                {
                    "type": "tool_use",
                    "name": name,
                    "input": input_payload,
                }
            )

            result_texts: list[str] = []
            result_raw = tool_call.get("result")
            if isinstance(result_raw, list):
                for result in result_raw:
                    if not isinstance(result, dict):
                        continue
                    function_response = result.get("functionResponse")
                    if isinstance(function_response, dict):
                        response_candidate = function_response.get("response")
                    else:
                        response_candidate = result.get("response")

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

            if any(result_texts):
                blocks.append({"type": "tool_result", "content": "\n\n".join(result_texts)})

        if not blocks and content_text:
            blocks.append({"type": "text", "text": str(content_text)})

        if not blocks:
            continue

        yield {
            "type": "assistant",
            "timestamp": timestamp,
            "message": {
                "role": "assistant",
                "content": blocks,
            },
        }


def render_agent_output(
    transcript_path: str,
    agent_name: AgentName,
    include_tools: bool = False,
    include_tool_results: bool = True,
    since_timestamp: Optional[datetime] = None,
    include_timestamps: bool = True,
) -> tuple[Optional[str], Optional[datetime]]:
    """Render markdown for assistant activity since the last user boundary or since_timestamp.

    Used for sequential, incremental output blocks. No truncation is applied;
    the adapter handles pagination/splitting for platform limits.

    Args:
        transcript_path: Path to transcript file
        agent_name: Agent name for iterator selection
        include_tools: Whether to include tool call blocks
        include_tool_results: Whether to include tool result blocks
        since_timestamp: Optional UTC datetime boundary. If provided, only returns activity AFTER this.
        include_timestamps: Whether to prefix blocks with [HH:MM:SS] timestamps

    Returns:
        Tuple of (markdown text or None, timestamp of last rendered entry or None)
    """
    entries = _get_entries_for_agent(transcript_path, agent_name)
    if not entries:
        return None, None

    # Find the lower boundary
    start_idx = 0
    if since_timestamp:
        if since_timestamp.tzinfo is None:
            since_timestamp = since_timestamp.replace(tzinfo=timezone.utc)

        # If we have a since_timestamp, only look at entries after it
        for i, entry in enumerate(entries):
            entry_ts_str = entry.get("timestamp")
            if isinstance(entry_ts_str, str):
                entry_dt = _parse_timestamp(entry_ts_str)
                if entry_dt:
                    if entry_dt.tzinfo is None:
                        entry_dt = entry_dt.replace(tzinfo=timezone.utc)

                    if entry_dt > since_timestamp:
                        logger.debug("[STD_RENDER] Found first new entry at index %d (ts: %s)", i, entry_ts_str)
                        start_idx = i
                        break
        else:
            # All entries are before or at since_timestamp
            return None, None
    else:
        # If no since_timestamp, find the last user boundary
        last_user_idx = -1
        for i in range(len(entries) - 1, -1, -1):
            entry = entries[i]
            message = entry.get("message")
            if not isinstance(message, dict) and entry.get("type") == "response_item":
                payload = entry.get("payload")
                if isinstance(payload, dict):
                    message = payload

            if isinstance(message, dict) and message.get("role") == "user":
                last_user_idx = i
                break
        start_idx = last_user_idx + 1
        logger.debug("[STD_RENDER] No cursor. Starting after last user message at index %d", start_idx)

    # Collect assistant activity from start_idx
    assistant_entries = entries[start_idx:]
    logger.debug(
        "Rendering incremental output",
        extra={
            "session": transcript_path,
            "start_idx": start_idx,
            "total_entries": len(entries),
            "assistant_entries": len(assistant_entries),
            "since_ts": since_timestamp,
        },
    )
    if not assistant_entries:
        return None, None

    lines: list[str] = []
    emitted = False
    last_entry_dt: Optional[datetime] = None

    for entry in assistant_entries:
        entry_ts_str = entry.get("timestamp")
        if isinstance(entry_ts_str, str):
            last_entry_dt = _parse_timestamp(entry_ts_str)

        message = entry.get("message")
        if not isinstance(message, dict) and entry.get("type") == "response_item":
            payload = entry.get("payload")
            if isinstance(payload, dict):
                message = payload

        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue

        content = message.get("content")
        if not isinstance(content, list):
            continue

        # Restore timestamp if we have a valid entry datetime
        time_prefix = ""
        if include_timestamps and last_entry_dt:
            time_prefix = f"[{last_entry_dt.strftime('%H:%M:%S')}] "

        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")

            if block_type in ("text", "output_text"):
                text = block.get("text", "")
                if text:
                    if lines:
                        lines.append("")
                    lines.append(f"{time_prefix}{text}")
                    emitted = True
            elif block_type == "thinking":
                thinking = block.get("thinking", "")
                if thinking:
                    if lines:
                        lines.append("")
                    formatted = _format_thinking(str(thinking))
                    lines.append(f"{time_prefix}{formatted}")
                    emitted = True
            elif block_type == "tool_use":
                if include_tools:
                    lines.append("")
                    _process_tool_use_block(block, time_prefix, lines)
                    emitted = True
            elif block_type == "tool_result":
                if include_tool_results:
                    lines.append("")
                    _process_tool_result_block(
                        block,
                        time_prefix,
                        lines,
                        collapse_tool_results=False,
                        max_chars=2000,
                    )
                    emitted = True

    if not emitted:
        return None, last_entry_dt

    result = "\n".join(lines).strip()
    return result, last_entry_dt


def get_assistant_messages_since(
    transcript_path: str,
    agent_name: AgentName,
    since_timestamp: Optional[datetime] = None,
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
        if since_timestamp.tzinfo is None:
            since_timestamp = since_timestamp.replace(tzinfo=timezone.utc)

        for i, entry in enumerate(entries):
            entry_ts_str = entry.get("timestamp")
            if isinstance(entry_ts_str, str):
                entry_dt = _parse_timestamp(entry_ts_str)
                if entry_dt:
                    if entry_dt.tzinfo is None:
                        entry_dt = entry_dt.replace(tzinfo=timezone.utc)

                    if entry_dt > since_timestamp:
                        start_idx = i
                        break
        else:
            return []
    else:
        # If no since_timestamp, find the last user boundary
        last_user_idx = -1
        for i in range(len(entries) - 1, -1, -1):
            entry = entries[i]
            message = entry.get("message") or entry.get("payload")
            if isinstance(message, dict) and message.get("role") == "user":
                last_user_idx = i
                break
        start_idx = last_user_idx + 1

    assistant_messages = []
    for entry in entries[start_idx:]:
        msg = entry.get("message") or entry.get("payload")
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            assistant_messages.append(msg)

    return assistant_messages


def count_renderable_assistant_blocks(
    transcript_path: str,
    agent_name: AgentName,
    since_timestamp: Optional[datetime] = None,
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


@dataclass(frozen=True)
class TranscriptParserInfo:
    """Metadata for formatting a native agent transcript."""

    display_name: str
    file_prefix: str
    parse: Callable[[str, str, Optional[str], Optional[str], int, bool], str]


AGENT_TRANSCRIPT_PARSERS: dict[AgentName, TranscriptParserInfo] = {
    AgentName.CLAUDE: TranscriptParserInfo("Claude Code", "claude", parse_claude_transcript),
    AgentName.GEMINI: TranscriptParserInfo("Gemini", "gemini", parse_gemini_transcript),
    AgentName.CODEX: TranscriptParserInfo("Codex", "codex", parse_codex_transcript),
}


def get_transcript_parser_info(agent_name: AgentName) -> TranscriptParserInfo:
    """Return metadata for the given agent's transcript parser."""
    return AGENT_TRANSCRIPT_PARSERS[agent_name]


def _get_entries_for_agent(
    transcript_path: str,
    agent_name: AgentName,
) -> Optional[list[dict[str, object]]]:  # guard: loose-dict - External entries
    """Load and return transcript entries for the given agent type.

    Returns None if path doesn't exist or agent type is unknown.
    """
    path = Path(transcript_path).expanduser()
    if not path.exists():
        return None

    if agent_name == AgentName.CLAUDE:
        return list(_iter_claude_entries(path))
    if agent_name == AgentName.GEMINI:
        return list(_iter_gemini_entries(path))
    if agent_name == AgentName.CODEX:
        return list(_iter_codex_entries(path))
    return None  # type: ignore[unreachable]  # Defensive fallback


def _extract_text_from_content(content: object, role: str) -> Optional[str]:
    """Extract text from message content based on role.

    guard: allow-string-compare
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        # User messages use "input_text" or "text", assistant uses "text" or "output_text"
        valid_types = ("input_text", "text") if role == "user" else ("text", "output_text")

        for block in content:
            if isinstance(block, dict) and block.get("type") in valid_types:
                return str(block.get("text", ""))

    return None


def _extract_last_message_by_role(
    transcript_path: str,
    agent_name: AgentName,
    target_role: str,
    count: int = 1,
) -> Optional[str]:
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
            message = entry.get("message")

            # Handle Codex "response_item" format where message is in payload
            if not isinstance(message, dict) and entry.get("type") == "response_item":
                payload = entry.get("payload")
                if isinstance(payload, dict):
                    message = payload

            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if not isinstance(role, str) or role != target_role:
                continue
            content = message.get("content")
            text = _extract_text_from_content(content, target_role)
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
) -> Optional[str]:
    """Extract the last user message from the transcript.

    Args:
        transcript_path: Path to transcript file
        agent_name: Agent type for entry iterator selection

    Returns:
        Last user message text or None if not found
    """
    return _extract_last_message_by_role(transcript_path, agent_name, "user")


def extract_last_agent_message(
    transcript_path: str,
    agent_name: AgentName,
    count: int = 1,
) -> Optional[str]:
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
        message = entry.get("message")
        if not isinstance(message, dict) and entry.get("type") == "response_item":
            payload = entry.get("payload")
            if isinstance(payload, dict):
                message = payload
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if not isinstance(role, str):
            continue
        content = message.get("content")
        text = _extract_text_from_content(content, role)
        if text:
            messages.append((role, text))
    return messages


def parse_session_transcript(
    transcript_path: str,
    title: str,
    *,
    agent_name: AgentName,
    since_timestamp: Optional[str] = None,
    until_timestamp: Optional[str] = None,
    tail_chars: int = 2000,
    escape_triple_backticks: bool = False,
    collapse_tool_results: bool = False,
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
    """

    parser_info = get_transcript_parser_info(agent_name)
    rendered = parser_info.parse(
        transcript_path,
        title,
        since_timestamp,
        until_timestamp,
        tail_chars,
        collapse_tool_results,
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


def extract_workdir_from_transcript(transcript_path: str) -> str | None:
    """Extract a working directory path from a native transcript file."""
    path = Path(transcript_path).expanduser()
    if not path.exists():
        return None

    def _collect_abs_paths(obj: object, out: list[str]) -> None:
        if isinstance(obj, dict):
            for value in obj.values():
                _collect_abs_paths(value, out)
        elif isinstance(obj, list):
            for item in obj:
                _collect_abs_paths(item, out)
        elif isinstance(obj, str) and Path(obj).is_absolute():
            out.append(obj.strip())

    def _derive_workdir_from_paths(paths: list[str]) -> str | None:
        if not paths:
            return None
        normalized: list[str] = []
        for raw in paths:
            candidate = raw.strip()
            if not candidate:
                continue
            p = Path(candidate)
            # If this looks like a file path, use its parent directory.
            if p.suffix and not candidate.endswith("/"):
                p = p.parent
            normalized.append(str(p))
        if not normalized:
            return None
        try:
            common = Path(os.path.commonpath(normalized))
        except ValueError:
            return normalized[0]
        if common.is_file():
            common = common.parent
        return str(common)

    try:
        if path.suffix == ".jsonl":
            with open(path, encoding="utf-8") as f:
                abs_paths: list[str] = []
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
                        payload = entry.get("payload")
                        found = _find_workdir_in_obj(payload)
                        if found:
                            return found
                    _collect_abs_paths(entry, abs_paths)
                    found = _find_workdir_in_obj(entry)
                    if found:
                        return found
            return _derive_workdir_from_paths(abs_paths)

        if path.suffix == ".json":
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            found = _find_workdir_in_obj(data)
            if found:
                return found
            abs_paths: list[str] = []
            _collect_abs_paths(data, abs_paths)
            return _derive_workdir_from_paths(abs_paths)
    except OSError:
        return None
    except json.JSONDecodeError:
        return None

    return None


def _escape_triple_backticks(text: str) -> str:
    """Escape triple backticks to avoid nested code block breakage."""
    return text.replace("```", "`\u200b``")
