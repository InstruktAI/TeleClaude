"""Formatting utilities for TUI display."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from rich.markup import escape as _rich_escape

# Width of the date suffix appended by ``format_time(with_date=True)``: ``-DD/MM``.
DATE_SUFFIX_WIDTH = 6


def format_time(iso_timestamp: str | None, *, with_date: bool = False) -> str:
    """Convert ISO timestamp to ``HH:MM:SS`` local time.

    With ``with_date``, append a fixed-width European ``-DD/MM`` suffix
    (``HH:MM:SS-DD/MM``) so the time column stays left-aligned while the date
    hangs off the right. Returns empty string if unavailable.
    """
    if not iso_timestamp:
        return ""
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        local_dt = dt.astimezone()
    except (ValueError, OSError):
        return ""
    base = local_dt.strftime("%H:%M:%S")
    if not with_date:
        return base
    return f"{base}-{local_dt.strftime('%d/%m')}"


def format_relative_time(iso_timestamp: str | None) -> str:
    """Convert ISO timestamp to relative time like '2m ago', '1h ago'.

    Returns empty string if unavailable.
    """
    if not iso_timestamp:
        return ""
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        now = datetime.now(UTC)
        delta = now - dt
        seconds = int(delta.total_seconds())
        if seconds < 0:
            return "now"
        if seconds < 60:
            return f"{seconds}s"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h"
        days = hours // 24
        return f"{days}d"
    except (ValueError, OSError):
        return ""


# Pattern matches /Users/<user>/... (macOS) or /home/<user>/... (Linux)
_HOME_PATH_PATTERN = re.compile(r"^(/(?:Users|home)/[^/]+)")


def shorten_path(path: str | None, max_len: int = 40) -> str:
    """Shorten a file path for display.

    Replaces home directory with ~ and truncates from the left.
    """
    if not path:
        return ""
    # Replace home dir prefix with ~
    shortened = _HOME_PATH_PATTERN.sub("~", path)
    if len(shortened) <= max_len:
        return shortened
    # Truncate from the left, keeping last segments
    return "..." + shortened[-(max_len - 3) :]


def truncate_text(text: str | None, max_len: int = 60) -> str:
    """Truncate text with ellipsis if too long."""
    if not text:
        return ""
    # Collapse whitespace
    text = " ".join(text.split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def format_countdown(until: str | None) -> str:
    """Format countdown string from ISO timestamp."""
    if not until:
        return "?"
    try:
        until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
        now = datetime.now(until_dt.tzinfo)
        delta = until_dt - now
        if delta.total_seconds() <= 0:
            return "soon"
        total_seconds = int(delta.total_seconds())
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes = remainder // 60
        if days > 0:
            return f"{days}d {hours}h"
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"
    except (ValueError, AttributeError):
        return "?"


def session_display_index(index: int, parent_index: str | None = None) -> str:
    """Build display index string like '1', '1.1', '1.2'."""
    if parent_index:
        return f"{parent_index}.{index}"
    return str(index)


def escape_markup(text: str) -> str:
    """Escape Rich markup characters so text renders as plain text in markup-aware widgets."""
    return _rich_escape(text)
