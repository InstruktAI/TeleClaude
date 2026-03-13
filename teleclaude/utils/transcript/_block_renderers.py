"""Block-level transcript rendering: process individual content blocks into markdown lines."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime

from ._parsers import normalize_transcript_entry_message
from ._utils import _format_thinking, _format_timestamp_prefix, _parse_timestamp


def iter_assistant_blocks(
    entries: Iterable[Mapping[str, object]],
) -> Iterator[tuple[dict[str, object], datetime | None]]:  # guard: loose-dict
    """Yield (block, entry_timestamp) for assistant content blocks only.

    Applies normalize_transcript_entry_message, role == "assistant" gate,
    and content-is-list check. Callers handle format-specific rendering.
    """
    for entry in entries:
        entry_dt: datetime | None = None
        entry_ts_str = entry.get("timestamp")
        if isinstance(entry_ts_str, str):
            entry_dt = _parse_timestamp(entry_ts_str)

        message = normalize_transcript_entry_message(entry)
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue

        content = message.get("content")
        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict):
                continue
            yield block, entry_dt


def _should_skip_entry(
    entry: dict[str, object],  # guard: loose-dict - External entry
    since_dt: datetime | None,
    until_dt: datetime | None,
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
    last_section: str | None,
    collapse_tool_results: bool,
    include_thinking: bool = True,
    include_tools: bool = True,
) -> str | None:  # guard: loose-dict - External entry
    """Process a transcript entry and append formatted content to lines.

    guard: allow-string-compare
    """
    entry_timestamp = entry.get("timestamp")
    entry_dt = None
    if isinstance(entry_timestamp, str):
        entry_dt = _parse_timestamp(entry_timestamp)
    time_prefix = _format_timestamp_prefix(entry_dt) if entry_dt else ""

    message = normalize_transcript_entry_message(entry)
    if not isinstance(message, dict):
        return last_section

    role = message.get("role")
    content: object = message.get("content", [])

    if not role or not isinstance(role, str):
        return last_section

    if isinstance(content, str):
        return _process_string_content(content, time_prefix, lines, last_section)

    if isinstance(content, list):
        return _process_list_content(
            content,
            role,
            time_prefix,
            lines,
            last_section,
            collapse_tool_results,
            include_thinking=include_thinking,
            include_tools=include_tools,
        )

    return last_section


def _process_string_content(content: str, time_prefix: str, lines: list[str], last_section: str | None) -> str:
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
    last_section: str | None,
    collapse_tool_results: bool,
    include_thinking: bool = True,
    include_tools: bool = True,
) -> str | None:
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
            if include_thinking:
                current_section = _process_thinking_block(block, time_prefix, lines, current_section)
        elif block_type == "tool_use":
            if include_tools:
                current_section = _process_tool_use_block(block, time_prefix, lines)
        elif block_type == "tool_result":
            if include_tools:
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
    last_section: str | None,
) -> str | None:
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
    last_section: str | None,
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


def _extract_tool_subject(block: dict[str, object]) -> str | None:  # guard: loose-dict - External block
    """Intelligently extract the 'subject' of a tool call from its arguments.

    Prioritizes paths, commands, patterns, and URLs.
    """
    input_data = block.get("input") or block.get("arguments")
    if not isinstance(input_data, dict):
        return None

    # Priority 1: Filesystem (paths)
    for key in ("path", "file_path", "dir_path", "filename", "project_path"):
        val = input_data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    # Priority 2: Shell/Execution (commands)
    for key in ("command", "script"):
        val = input_data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().split("\n")[0]  # First line only

    # Priority 3: Search/Query
    for key in ("pattern", "query", "regex", "search"):
        val = input_data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    # Priority 4: Web/Logic (URLs, Slugs)
    for key in ("url", "slug", "session_id", "channel"):
        val = input_data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    return None


def _process_tool_use_block(
    block: dict[str, object],  # guard: loose-dict - External block
    time_prefix: str,
    lines: list[str],
) -> str:
    """Process tool use block.

    guard: allow-string-compare
    """
    tool_name = str(block.get("name", "unknown"))
    # Truncate at first newline, open paren, or open brace to ensure single-line name only
    tool_name_safe = tool_name.split("\n")[0].split("(")[0].split("{")[0].strip()

    # 1. Start with the base decoration
    # **`tool_name`**
    prefix = time_prefix
    formatted_name = f"**`{tool_name_safe}`**"

    # 2. Extract subject and calculate budget
    subject = _extract_tool_subject(block)

    # Length budget: TOTAL length (prefix + name + subject decoration) <= 70.
    base_len = len(time_prefix) + len(tool_name_safe)
    if subject:
        base_len += 2  # for ': '

    budget = max(0, 70 - base_len)

    if subject and budget > 0:
        if len(subject) > budget:
            subject = subject[: budget - 1] + "…"
        content = f"{formatted_name}: `{subject}`"
    else:
        content = formatted_name

    lines.append("")
    lines.append(f"{prefix}{content}")
    return "tool_use"


def _process_tool_result_block(
    block: dict[str, object],  # guard: loose-dict - External block
    time_prefix: str,
    lines: list[str],
    collapse_tool_results: bool,
    max_chars: int | None = None,
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
