"""Shared utilities: timestamp parsing, thinking formatting, tail limiting."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from teleclaude.core.dates import format_local_datetime

CHECKPOINT_JSONL_TAIL_ENTRIES = 2000
CHECKPOINT_JSONL_TAIL_READ_BYTES = 1_048_576


def _parse_timestamp(ts: str) -> datetime | None:
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
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                continue
        # Fallback: fromisoformat handles most cases
        parsed = datetime.fromisoformat(ts_clean)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
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
        dt = dt.replace(tzinfo=UTC)
    local_dt = dt.astimezone()
    now = datetime.now().astimezone()

    # If same day, just show time
    if local_dt.date() == now.date():
        return f"{format_local_datetime(dt, include_date=False)} · "

    # Different day, show full date + time
    return f"{format_local_datetime(dt, include_date=True)} · "


_THINKING_HEADING_RE = re.compile(r"^(\s{0,3}#{1,6}\s+)(.+)$")
_THINKING_LIST_RE = re.compile(r"^(\s{0,6}(?:[-+*]|\d+\.)\s+)(.+)$")
_THINKING_QUOTE_RE = re.compile(r"^(\s*>+\s?)(.+)$")
_THINKING_RULE_RE = re.compile(r"^\s*[-*_]{3,}\s*$")


def _wrap_thinking_emphasis(text: str) -> str:
    """Wrap non-empty text in markdown emphasis while preserving surrounding spaces."""
    if not text.strip():
        return text

    leading = len(text) - len(text.lstrip())
    trailing = len(text) - len(text.rstrip())
    core_start = leading
    core_end = len(text) - trailing if trailing else len(text)
    core = text[core_start:core_end]
    core_stripped = core.strip()
    if not core_stripped:
        return text

    # Avoid double wrapping lines that already look emphasized.
    if (core_stripped.startswith("*") and core_stripped.endswith("*") and len(core_stripped) >= 2) or (
        core_stripped.startswith("_") and core_stripped.endswith("_") and len(core_stripped) >= 2
    ):
        return text

    return f"{text[:core_start]}*{core}*{text[core_end:]}"


def _italicize_thinking_line(line: str) -> str:
    """Italicize a non-code thinking line while preserving markdown structure where possible."""
    stripped = line.strip()
    if not stripped:
        return line
    if _THINKING_RULE_RE.match(line):
        return line
    if stripped.startswith("|") and stripped.endswith("|"):
        return line

    for pattern in (_THINKING_HEADING_RE, _THINKING_LIST_RE, _THINKING_QUOTE_RE):
        match = pattern.match(line)
        if match:
            prefix, remainder = match.groups()
            if not remainder.strip():
                return line
            return f"{prefix}{_wrap_thinking_emphasis(remainder)}"

    return _wrap_thinking_emphasis(line)


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
            result_lines.append(_italicize_thinking_line(str(line)))

    # Add blank line after thinking block
    result_lines.append("")

    return "\n".join(result_lines)


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


def _escape_triple_backticks(text: str) -> str:
    """Escape triple backticks to avoid nested code block breakage."""
    return text.replace("```", "`\u200b``")
