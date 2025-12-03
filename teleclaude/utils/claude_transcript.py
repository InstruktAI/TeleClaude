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

    # Parse timestamp filters
    since_dt = _parse_timestamp(since_timestamp) if since_timestamp else None
    until_dt = _parse_timestamp(until_timestamp) if until_timestamp else None

    lines: list[str] = []

    # Add title from session
    lines.append(f"# {title}")
    lines.append("")

    last_section: Optional[str] = None

    try:
        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)

                # Skip summary entries
                if entry.get("type") == "summary":
                    continue

                # Get timestamp from entry
                entry_timestamp = entry.get("timestamp")
                entry_dt = _parse_timestamp(entry_timestamp) if entry_timestamp else None

                # Apply timestamp filters
                if since_dt and entry_dt and entry_dt < since_dt:
                    continue
                if until_dt and entry_dt and entry_dt > until_dt:
                    continue

                # Format timestamp for display (compact: HH:MM:SS or full if different day)
                time_prefix = _format_timestamp_prefix(entry_dt) if entry_dt else ""

                # Extract message content (nested in 'message' field for Claude Code transcripts)
                message = entry.get("message", {})
                role = message.get("role")
                content = message.get("content", [])

                # Skip if no role
                if not role:
                    continue

                # Process content blocks - separate tool_use/tool_result from text
                if isinstance(content, str):
                    # User message (string content)
                    # Only add header if role changed OR we have a timestamp (individual entry)
                    if last_section != "user" or time_prefix:
                        lines.append("")
                        lines.append(f"## {time_prefix}👤 User")
                        lines.append("")
                        last_section = "user"
                    lines.append(content)
                elif isinstance(content, list):
                    # Assistant or user message with blocks
                    for block in content:
                        block_type = block.get("type")

                        if block_type == "text":
                            # Text from assistant
                            if role == "assistant" and last_section != "assistant":
                                lines.append("")
                                lines.append(f"## {time_prefix}🤖 Assistant")
                                lines.append("")
                                last_section = "assistant"
                            text = block.get("text", "")
                            lines.append(text)

                        elif block_type == "thinking":
                            # Thinking block (only in assistant messages)
                            if last_section != "assistant":
                                lines.append("")
                                lines.append(f"## {time_prefix}🤖 Assistant")
                                lines.append("")
                                last_section = "assistant"
                            formatted_thinking = _format_thinking(block.get("thinking", ""))
                            lines.append(formatted_thinking)

                        elif block_type == "tool_use":
                            # Tool call - single line with serialized JSON
                            tool_name = block.get("name", "unknown")
                            tool_input = block.get("input", {})
                            serialized_input = json.dumps(tool_input)
                            lines.append("")
                            lines.append(f"{time_prefix}🔧 **TOOL CALL:** {tool_name} {serialized_input}")
                            last_section = "tool_use"

                        elif block_type == "tool_result":
                            # Tool response - blockquote expandable format
                            is_error = block.get("is_error", False)
                            status_emoji = "❌" if is_error else "✅"
                            content_data = block.get("content", "")
                            lines.append("")
                            lines.append(f"{time_prefix}{status_emoji} **TOOL RESPONSE:**")
                            lines.append("")
                            lines.append("<blockquote expandable>")
                            lines.append(str(content_data))
                            lines.append("</blockquote>")
                            last_section = "tool_result"

    except Exception as e:
        return f"Error parsing transcript: {e}"

    result = "\n".join(lines)

    # Apply tail_chars limit (from end of content)
    if tail_chars > 0 and len(result) > tail_chars:
        # Find a good break point (start of a section header)
        truncated = result[-tail_chars:]
        # Try to find a section header to start cleanly
        header_pos = truncated.find("\n## ")
        if header_pos != -1 and header_pos < 500:  # Only if within first 500 chars
            truncated = truncated[header_pos + 1 :]  # Skip the leading newline
        result = f"[...truncated, showing last {tail_chars} chars...]\n\n{truncated}"

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
