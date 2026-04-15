"""Gemini-native session-scoping extractor."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from .._types import ScopeMode
from ._common import _normalize_workspace_path

__all__ = ["collect_gemini_paths"]

_GEMINI_MUTATORS = {"edit", "writefile"}


def _normalize_gemini_tool_name(tool_call: Mapping[str, object]) -> str:
    raw_name = tool_call.get("name")
    if not isinstance(raw_name, str):
        raw_name = tool_call.get("displayName")
    return str(raw_name or "").strip().lower()


def _extract_gemini_tool_paths(
    message: Mapping[str, object],
    workspace_root: str | None,
) -> set[str]:
    if message.get("type") != "gemini":
        return set()

    tool_calls = message.get("toolCalls")
    if not isinstance(tool_calls, list):
        return set()

    paths: set[str] = set()
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        tool_name = _normalize_gemini_tool_name(tool_call)
        if tool_name not in _GEMINI_MUTATORS:
            continue
        status = str(tool_call.get("status", "")).strip().lower()
        if status != "success":
            continue
        args = tool_call.get("args")
        if not isinstance(args, dict):
            continue
        file_path = args.get("file_path")
        if isinstance(file_path, str) and file_path.strip():
            normalized = _normalize_workspace_path(file_path, workspace_root)
            if normalized:
                paths.add(normalized)
    return paths


def collect_gemini_paths(
    *,
    transcript_path: str | None,
    native_session_id: str | None = None,
    workspace_root: str | None,
    scope_mode: ScopeMode,
) -> tuple[set[str], str]:
    """Collect Gemini-owned paths from successful explicit file tools only."""
    del native_session_id
    if not transcript_path:
        return set(), "gemini_structured"

    raw_document = json.loads(Path(transcript_path).read_text(encoding="utf-8"))
    if not isinstance(raw_document, dict):
        return set(), "gemini_structured"
    raw_messages = raw_document.get("messages")
    if not isinstance(raw_messages, list):
        return set(), "gemini_structured"
    messages = [message for message in raw_messages if isinstance(message, dict)]

    start_index = 0
    if scope_mode == "turn_delta":
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].get("type") == "user":
                start_index = index + 1
                break

    scoped_paths: set[str] = set()
    for message in messages[start_index:]:
        scoped_paths.update(_extract_gemini_tool_paths(message, workspace_root))

    return scoped_paths, "gemini_structured"
