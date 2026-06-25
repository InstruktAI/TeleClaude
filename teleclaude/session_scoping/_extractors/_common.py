"""Shared extractor helpers for session scoping."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from teleclaude.shell_path_parser import (
    command_likely_mutates_files as _command_likely_mutates_files,
)
from teleclaude.shell_path_parser import extract_shell_command as _extract_shell_command
from teleclaude.shell_path_parser import extract_shell_touched_paths as _extract_shell_touched_paths
from teleclaude.utils.transcript import TurnTimeline

from .._types import ScopeMode


class ExtractorFunction(Protocol):
    """Typed contract for agent-native path extractors."""

    def __call__(
        self,
        *,
        transcript_path: str | None,
        native_session_id: str | None,
        workspace_root: str | None,
        scope_mode: ScopeMode,
    ) -> tuple[set[str], str]: ...


__all__ = [
    "ExtractorFunction",
    "extract_shell_paths_from_timeline",
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
    for key in ("file_path", "path", "filepath", "target_file"):
        value = input_data.get(key)
        if isinstance(value, str):
            normalized = _normalize_workspace_path(value, workspace_root)
            if normalized:
                paths.add(normalized)
    for key in ("file_paths", "paths"):
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


def extract_shell_paths_from_timeline(
    timeline: TurnTimeline,
    *,
    workspace_root: str | None,
    allowed_tools: set[str],
) -> set[str]:
    """Collect explicit file paths from successful shell-like mutators."""
    touched_paths: set[str] = set()
    for record in timeline.tool_calls:
        tool_name = _canonical_tool_name(record.tool_name)
        if tool_name not in allowed_tools or record.had_error:
            continue
        command = _extract_shell_command(record.input_data)
        if not _command_likely_mutates_files(command):
            continue
        touched_paths.update(
            _extract_shell_touched_paths(command, lambda path: _normalize_workspace_path(path, workspace_root))
        )
    return touched_paths


def extract_structured_paths_from_timeline(
    timeline: TurnTimeline,
    *,
    workspace_root: str | None,
    allowed_tools: set[str],
) -> set[str]:
    """Collect explicit structured-mutator file paths from a normalized timeline."""
    touched_paths: set[str] = set()
    for record in timeline.tool_calls:
        tool_name = _canonical_tool_name(record.tool_name)
        if tool_name not in allowed_tools or record.had_error:
            continue
        touched_paths.update(_extract_path_values(record.input_data, workspace_root))
        if tool_name == "apply_patch":
            for key in ("input", "patch", "raw_arguments", "command", "cmd"):
                value = record.input_data.get(key)
                if isinstance(value, str):
                    touched_paths.update(_extract_apply_patch_paths(value, workspace_root))
    return touched_paths
