"""Helpers for tool activity labels shown in real-time UI."""

from __future__ import annotations

from collections.abc import Mapping

TOOL_ACTIVITY_PREVIEW_MAX_CHARS = 70


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


def build_tool_preview(
    *,
    tool_name: str | None,
    raw_payload: Mapping[str, object] | None,
) -> str | None:
    """Build compact tool preview text for UI from contract payload fields."""
    command: str | None = None
    file_path: str | None = None
    description: str | None = None

    if raw_payload:
        tool_input = raw_payload.get("tool_input")
        if isinstance(tool_input, Mapping):
            command = _as_non_empty_str(tool_input.get("command"))
            file_path = _as_non_empty_str(tool_input.get("file_path"))
            description = _as_non_empty_str(tool_input.get("description"))

    if command:
        return truncate_tool_preview(f"{tool_name or ''} {command}".strip())
    if file_path:
        return truncate_tool_preview(f"{tool_name or ''} {file_path}".strip())
    if description:
        return truncate_tool_preview(f"{tool_name or ''} {description}".strip())
    return truncate_tool_preview(tool_name)
