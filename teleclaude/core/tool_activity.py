"""Helpers for tool activity labels shown in real-time UI."""

from __future__ import annotations

import re
from collections.abc import Mapping

TOOL_ACTIVITY_PREVIEW_MAX_CHARS = 70
_TREE_PREFIX_RE = re.compile(r"^(?:[│┃┆┊|]+\s*|[├└]\s*)+")
_INLINE_TREE_MARKER_RE = re.compile(r"\s[├└]\s+")
_NEXT_WORK_CALL_RE = re.compile(r"telec todo work\(\s*slug\s*=\s*([^)]+?)\s*\)")
_NEXT_PREPARE_CALL_RE = re.compile(r"telec todo prepare\(\s*slug\s*=\s*([^)]+?)\s*\)")
_NEXT_WORK_EMPTY_CALL_RE = re.compile(r"telec todo work\(\s*\)")
_NEXT_PREPARE_EMPTY_CALL_RE = re.compile(r"telec todo prepare\(\s*\)")
_MAPPED_TOOL_NAMES: dict[str, str] = {
    "next_work": "telec todo work",
    "next_prepare": "telec todo prepare",
    "next_maintain": "telec todo maintain",
    "mark_phase": "telec todo mark-phase",
    "set_dependencies": "telec todo set-deps",
    "run_agent_command": "telec sessions run",
    "get_session_data": "telec sessions tail",
    "send_message": "telec sessions send",
    "start_session": "telec sessions start",
    "end_session": "telec sessions end",
    "list_sessions": "telec sessions list",
    "stop_notifications": "telec sessions unsubscribe",
    "send_result": "telec sessions result",
    "send_file": "telec sessions file",
    "render_widget": "telec sessions widget",
    "escalate": "telec sessions escalate",
    "list_computers": "telec computers list",
    "list_projects": "telec projects list",
    "channels_list": "telec channels list",
    "publish": "telec channels publish",
}
_MAPPED_TOOL_NAME_RE = re.compile(
    r"\b(" + "|".join(re.escape(name) for name in sorted(_MAPPED_TOOL_NAMES, key=len, reverse=True)) + r")\b"
)

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


def _normalize_tool_invocations(text: str) -> str:
    """Normalize tool invocation snippets to telec CLI command style."""

    def _strip_quotes(value: str) -> str:
        trimmed = value.strip()
        if len(trimmed) >= 2 and trimmed[0] == trimmed[-1] and trimmed[0] in {"'", '"'}:
            return trimmed[1:-1]
        return trimmed

    def _replace_slug_call(match: re.Match[str], command: str) -> str:
        slug_expr = _strip_quotes(match.group(1))
        return f"{command} {slug_expr}".strip()

    normalized = _NEXT_WORK_CALL_RE.sub(lambda m: _replace_slug_call(m, "telec todo work"), text)
    normalized = _NEXT_PREPARE_CALL_RE.sub(lambda m: _replace_slug_call(m, "telec todo prepare"), normalized)
    normalized = _NEXT_WORK_EMPTY_CALL_RE.sub("telec todo work", normalized)
    normalized = _NEXT_PREPARE_EMPTY_CALL_RE.sub("telec todo prepare", normalized)

    def _replace_name(match: re.Match[str]) -> str:
        return _MAPPED_TOOL_NAMES.get(match.group(1), match.group(1))

    return _MAPPED_TOOL_NAME_RE.sub(_replace_name, normalized)


def truncate_tool_preview(text: str | None) -> str | None:
    """Return first TOOL_ACTIVITY_PREVIEW_MAX_CHARS chars or None."""
    if not text:
        return None
    clipped = text.strip()
    if not clipped:
        return None
    clipped = _TREE_PREFIX_RE.sub("", clipped)
    clipped = _INLINE_TREE_MARKER_RE.sub(" ", clipped)
    clipped = _normalize_tool_invocations(clipped).strip()
    if not clipped:
        return None
    return clipped[:TOOL_ACTIVITY_PREVIEW_MAX_CHARS]


def extract_tool_name(raw_payload: Mapping[str, object] | None) -> str | None:
    """Extract normalized tool name from hook payload."""
    if not raw_payload:
        return None
    raw_tool = raw_payload.get("tool_name") or raw_payload.get("toolName")
    text = _as_non_empty_str(raw_tool)
    if not text:
        return None
    return _normalize_tool_invocations(text)


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
        # Synthetic turn events can already provide a best-effort preview string.
        preview_text = _as_non_empty_str(raw_payload.get("tool_preview")) or _as_non_empty_str(
            raw_payload.get("toolPreview")
        )
        if preview_text:
            return truncate_tool_preview(preview_text)

        tool_input = raw_payload.get("tool_input")
        if isinstance(tool_input, Mapping):
            detail = _extract_detail(tool_input)

    if detail:
        return truncate_tool_preview(f"{tool_name or ''} {detail}".strip())
    return truncate_tool_preview(tool_name)
