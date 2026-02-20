"""Helpers for tool activity labels shown in real-time UI."""

from __future__ import annotations

from collections.abc import Mapping

TOOL_ACTIVITY_PREVIEW_MAX_CHARS = 70

# Fields checked in priority order for a useful preview snippet.
_PREVIEW_FIELDS = (
    "command",
    "file_path",
    "pattern",
    "query",
    "url",
    "notebook_path",
    "skill",
    "prompt",
    "description",
)


def _first_line(text: str) -> str:
    """Return text up to the first newline."""
    idx = text.find("\n")
    return text[:idx] if idx >= 0 else text


def _as_non_empty_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text


def truncate_tool_preview(text: str | None) -> str | None:
    """Return first TOOL_ACTIVITY_PREVIEW_MAX_CHARS chars or None."""
    if not text:
        return None
    clipped = text.strip()
    if not clipped:
        return None
    return clipped[:TOOL_ACTIVITY_PREVIEW_MAX_CHARS]


def extract_tool_name(raw_payload: Mapping[str, object] | None) -> str | None:
    """Extract normalized tool name from hook payload."""
    if not raw_payload:
        return None
    raw_tool = raw_payload.get("tool_name") or raw_payload.get("toolName")
    return _as_non_empty_str(raw_tool)


def _extract_detail(tool_input: Mapping[str, object]) -> str | None:
    """Extract the most interesting detail string from tool_input.

    Checks known high-value fields first, then falls back to the first
    non-empty string value it finds.  Only the first line is kept.
    """
    # Priority fields
    for field in _PREVIEW_FIELDS:
        val = _as_non_empty_str(tool_input.get(field))
        if val:
            return _first_line(val)

    # Generic fallback: first string value that isn't empty
    for val in tool_input.values():
        text = _as_non_empty_str(val)
        if text:
            return _first_line(text)

    return None


def build_tool_preview(
    *,
    tool_name: str | None,
    raw_payload: Mapping[str, object] | None,
) -> str | None:
    """Build compact tool preview text for UI from contract payload fields."""
    detail: str | None = None

    if raw_payload:
        tool_input = raw_payload.get("tool_input")
        if isinstance(tool_input, Mapping):
            detail = _extract_detail(tool_input)

    if detail:
        return truncate_tool_preview(f"{tool_name or ''} {detail}".strip())
    return truncate_tool_preview(tool_name)
