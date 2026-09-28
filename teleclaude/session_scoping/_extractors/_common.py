"""Shared extractor helpers for session scoping."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript import TurnTimeline
from teleclaude.utils.transcript._tool_calls import ToolCallRecord

_PATH_FIELDS = ("file_path", "path", "filepath", "target_file", "notebook_path", "TargetFile")
_PATH_LIST_FIELDS = ("file_paths", "paths")
_PATCH_FIELDS = ("input", "patch", "raw_arguments", "command", "cmd")
_APPLY_PATCH_TOOL = "apply_patch"
CERTAIN_EDIT_TOOLS: Mapping[AgentName, frozenset[str]] = MappingProxyType(
    {
        AgentName.CLAUDE: frozenset({"write", "edit", "multiedit", "notebookedit"}),
        AgentName.CODEX: frozenset({"edit", "write", "multiedit", "apply_patch", "notebookedit"}),
        AgentName.DEEPSEEK: frozenset({"write", "edit"}),
        AgentName.GEMINI: frozenset({"replace_file_content", "write_to_file", "multi_replace_file_content"}),
    }
)


__all__ = [
    "extract_structured_paths_from_timeline",
]


def _canonical_tool_name(tool_name: str) -> str:
    normalized = tool_name.strip().lower()
    if "." in normalized:
        normalized = normalized.rsplit(".", 1)[-1]
    return normalized


def _normalize_workspace_path(path: str, workspace_root: str | None) -> str:
    raw = path.strip()
    if not raw:
        return ""
    candidate = Path(raw)
    if candidate.is_absolute():
        if not workspace_root:
            return ""
        try:
            candidate = candidate.relative_to(Path(workspace_root))
        except ValueError:
            return ""
    return candidate.as_posix().removeprefix("./")


def _extract_apply_patch_paths(patch_text: str, workspace_root: str | None) -> set[str]:
    prefixes = (
        "*** Update File:",
        "*** Add File:",
        "*** Delete File:",
        "*** Move to:",
    )
    paths: set[str] = set()
    for line in patch_text.splitlines():
        stripped = line.strip()
        for prefix in prefixes:
            if not stripped.startswith(prefix):
                continue
            normalized = _normalize_workspace_path(stripped[len(prefix) :].strip(), workspace_root)
            if normalized:
                paths.add(normalized)
    return paths


def _extract_path_values(
    input_data: Mapping[str, object],
    workspace_root: str | None,
) -> set[str]:
    paths: set[str] = set()
    for key in _PATH_FIELDS:
        value = input_data.get(key)
        if isinstance(value, str):
            normalized = _normalize_workspace_path(value, workspace_root)
            if normalized:
                paths.add(normalized)
    for key in _PATH_LIST_FIELDS:
        value = input_data.get(key)
        if not isinstance(value, list):
            continue
        for entry in value:
            if not isinstance(entry, str):
                continue
            normalized = _normalize_workspace_path(entry, workspace_root)
            if normalized:
                paths.add(normalized)
    return paths


def extract_structured_paths_from_timeline(
    timeline: TurnTimeline,
    *,
    workspace_root: str | None,
    allowed_tools: frozenset[str],
) -> set[str]:
    """Collect explicit structured-mutator file paths from a normalized timeline."""
    touched_paths: set[str] = set()
    for record in timeline.tool_calls:
        touched_paths.update(_extract_paths_from_record(record, workspace_root, allowed_tools))
    return touched_paths


def _extract_paths_from_record(
    record: ToolCallRecord,
    workspace_root: str | None,
    structured_tools: frozenset[str],
) -> set[str]:
    """Collect successful structured mutations from one tool record."""
    if record.had_error or not record.result_observed:
        return set()
    tool_name = _canonical_tool_name(record.tool_name)
    paths: set[str] = set()
    if tool_name in structured_tools:
        paths.update(_extract_path_values(record.input_data, workspace_root))
        if tool_name == _APPLY_PATCH_TOOL:
            for key in _PATCH_FIELDS:
                value = record.input_data.get(key)
                if isinstance(value, str):
                    paths.update(_extract_apply_patch_paths(value, workspace_root))
    return paths
