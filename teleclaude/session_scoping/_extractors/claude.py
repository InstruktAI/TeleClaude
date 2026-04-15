"""Claude-native session-scoping extractor."""

from __future__ import annotations

from collections.abc import Mapping

from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript import extract_effective_tool_calls
from teleclaude.utils.transcript._iterators import _get_entries_for_agent
from teleclaude.utils.transcript._tool_calls import _find_turn_start_idx

from .._types import ScopeMode
from ._common import _normalize_workspace_path, extract_structured_paths_from_timeline

__all__ = ["collect_claude_paths"]

_CLAUDE_FALLBACK_MUTATORS = {"write", "edit"}


def _snapshot_paths_from_entry(entry: Mapping[str, object], workspace_root: str | None) -> set[str]:
    snapshot = entry.get("snapshot")
    if not isinstance(snapshot, dict):
        payload = entry.get("payload")
        if isinstance(payload, dict) and payload.get("type") == "file-history-snapshot":
            snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        return set()

    tracked_file_backups = snapshot.get("trackedFileBackups")
    if not isinstance(tracked_file_backups, dict):
        return set()

    paths: set[str] = set()
    for key in tracked_file_backups:
        if not isinstance(key, str):
            continue
        normalized = _normalize_workspace_path(key, workspace_root)
        if not normalized:
            continue
        paths.add(normalized)
    return paths


def collect_claude_paths(
    *,
    transcript_path: str | None,
    native_session_id: str | None = None,
    workspace_root: str | None,
    scope_mode: ScopeMode,
) -> tuple[set[str], str]:
    """Collect Claude-owned paths from file-history snapshots or structured tool use."""
    del native_session_id
    if not transcript_path:
        return set(), "claude_structured_fallback"

    entries = _get_entries_for_agent(transcript_path, AgentName.CLAUDE) or []
    turn_start_idx = _find_turn_start_idx(entries, scope_mode == "session_dirty")

    previous_snapshot_paths: set[str] = set()
    current_snapshot_paths: set[str] = set()
    for index, entry in enumerate(entries):
        snapshot_paths = _snapshot_paths_from_entry(entry, workspace_root)
        if not snapshot_paths:
            continue
        if index < turn_start_idx:
            previous_snapshot_paths = snapshot_paths
        else:
            current_snapshot_paths = snapshot_paths

    structured_fallback = extract_structured_paths_from_timeline(
        extract_effective_tool_calls(
            transcript_path,
            AgentName.CLAUDE,
            scope="session" if scope_mode == "session_dirty" else "turn",
        ),
        workspace_root=workspace_root,
        allowed_tools=_CLAUDE_FALLBACK_MUTATORS,
    )

    if not current_snapshot_paths:
        return structured_fallback, "claude_structured_fallback"
    if scope_mode == "turn_delta":
        return (current_snapshot_paths - previous_snapshot_paths) | structured_fallback, "claude_file_history"
    return current_snapshot_paths | structured_fallback, "claude_file_history"
