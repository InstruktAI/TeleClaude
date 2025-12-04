"""Parse and convert Claude Code session transcripts to markdown."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


def parse_claude_transcript(
    transcript_path: str,
    title: str,
    since_timestamp: Optional[str] = None,
    until_timestamp: Optional[str] = None,
    tail_chars: int = 5000,
) -> str:
    """Convert Claude Code JSONL transcript to markdown with filtering.

    Args:
        transcript_path: Path to Claude session .jsonl file
        title: Session title for header
        since_timestamp: Optional ISO 8601 UTC start filter (inclusive)
        until_timestamp: Optional ISO 8601 UTC end filter (inclusive)
        tail_chars: Max characters to return from end (default 5000, 0 for unlimited)

    Returns:
        Markdown formatted conversation with timestamps on each section
    """
    path = Path(transcript_path).expanduser()
    if not path.exists():
        return f"Transcript file not found: {transcript_path}"

    since_dt = _parse_timestamp(since_timestamp) if since_timestamp else None
    until_dt = _parse_timestamp(until_timestamp) if until_timestamp else None

    lines: list[str] = [f"# {title}", ""]
    last_section: Optional[str] = None

    try:
        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue

                entry = json.loads(line)  # type: ignore[misc]

                if _should_skip_entry(entry, since_dt, until_dt):  # type: ignore[misc]
                    continue

                last_section = _process_entry(entry, lines, last_section)  # type: ignore[misc]

    except Exception as e:
        return f"Error parsing transcript: {e}"

    result = "\n".join(lines)
    return _apply_tail_limit(result, tail_chars)


def _should_skip_entry(entry: dict[str, object], since_dt: Optional[datetime], until_dt: Optional[datetime]) -> bool:
    """Check if entry should be skipped based on type and timestamp filters."""
    if entry.get("type") == "summary":
        return True

    entry_timestamp = entry.get("timestamp")
    if isinstance(entry_timestamp, str):
        entry_dt = _parse_timestamp(entry_timestamp)
        if since_dt and entry_dt and entry_dt < since_dt:
            return True
        if until_dt and entry_dt and entry_dt > until_dt:
            return True

    return False


def _process_entry(entry: dict[str, object], lines: list[str], last_section: Optional[str]) -> Optional[str]:
    """Process a transcript entry and append formatted content to lines."""
    entry_timestamp = entry.get("timestamp")
    entry_dt = None
    if isinstance(entry_timestamp, str):
        entry_dt = _parse_timestamp(entry_timestamp)
    time_prefix = _format_timestamp_prefix(entry_dt) if entry_dt else ""

    message = entry.get("message", {})
    if not isinstance(message, dict):
        return last_section

    role = message.get("role")
    content: object = message.get("content", [])

    if not role or not isinstance(role, str):
        return last_section

    if isinstance(content, str):
        return _process_string_content(content, time_prefix, lines, last_section)

    if isinstance(content, list):
        return _process_list_content(content, role, time_prefix, lines, last_section)

    return last_section


def _process_string_content(content: str, time_prefix: str, lines: list[str], last_section: Optional[str]) -> str:
    """Process string content (user message)."""
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
) -> Optional[str]:
    """Process list of content blocks."""
    current_section = last_section

    for block in content:
        if not isinstance(block, dict):
            continue

        block_type = block.get("type")
        if not isinstance(block_type, str):
            continue

        if block_type == "text":
            current_section = _process_text_block(block, role, time_prefix, lines, current_section)
        elif block_type == "thinking":
            current_section = _process_thinking_block(block, time_prefix, lines, current_section)
        elif block_type == "tool_use":
            current_section = _process_tool_use_block(block, time_prefix, lines)
        elif block_type == "tool_result":
            current_section = _process_tool_result_block(block, time_prefix, lines)

    return current_section


def _process_text_block(
    block: dict[str, object],
    role: str,
    time_prefix: str,
    lines: list[str],
    last_section: Optional[str],
) -> Optional[str]:
    """Process text block from assistant."""
    if role == "assistant" and last_section != "assistant":
        lines.append("")
        lines.append(f"## {time_prefix}🤖 Assistant")
        lines.append("")
    text = block.get("text", "")
    lines.append(str(text))
    return "assistant" if role == "assistant" else last_section


def _process_thinking_block(
    block: dict[str, object], time_prefix: str, lines: list[str], last_section: Optional[str]
) -> str:
    """Process thinking block."""
    if last_section != "assistant":
        lines.append("")
        lines.append(f"## {time_prefix}🤖 Assistant")
        lines.append("")
    thinking = block.get("thinking", "")
    formatted_thinking = _format_thinking(str(thinking))
    lines.append(formatted_thinking)
    return "assistant"


def _process_tool_use_block(block: dict[str, object], time_prefix: str, lines: list[str]) -> str:
    """Process tool use block."""
    tool_name = block.get("name", "unknown")
    tool_input = block.get("input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}
    serialized_input = json.dumps(tool_input)
    lines.append("")
    lines.append(f"{time_prefix}🔧 **TOOL CALL:** {tool_name} {serialized_input}")
    return "tool_use"


def _process_tool_result_block(block: dict[str, object], time_prefix: str, lines: list[str]) -> str:
    """Process tool result block."""
    is_error = block.get("is_error", False)
    status_emoji = "❌" if is_error else "✅"
    content_data = block.get("content", "")
    lines.append("")
    lines.append(f"{time_prefix}{status_emoji} **TOOL RESPONSE:**")
    lines.append("")
    lines.append("<blockquote expandable>")
    lines.append(str(content_data))
    lines.append("</blockquote>")
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
                return datetime.strptime(ts_clean, fmt)
            except ValueError:
                continue
        # Fallback: fromisoformat handles most cases
        return datetime.fromisoformat(ts_clean)
    except (ValueError, TypeError):
        return None


def _format_timestamp_prefix(dt: datetime) -> str:
    """Format datetime as prefix for section headers.

    Args:
        dt: datetime object

    Returns:
        Formatted string like "14:25:33 · " or "2025-11-11 14:25:33 · "
    """
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()

    # If same day, just show time
    if dt.date() == now.date():
        return f"{dt.strftime('%H:%M:%S')} · "

    # Different day, show full date + time
    return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} · "


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
