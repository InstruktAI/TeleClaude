"""Validate and persist declarations backed by certain edit-tool calls."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict, cast

from teleclaude.config._file_io import FileTransaction, file_transaction
from teleclaude.core.agents import AgentName
from teleclaude.paths import session_tmp_dir
from teleclaude.project_root import resolve_invocation_roots
from teleclaude.quality import scope as quality_scope
from teleclaude.session_scoping import certain_edit_paths, declare
from teleclaude.session_scoping._extractors._common import CERTAIN_EDIT_TOOLS, extract_structured_paths_from_timeline
from teleclaude.utils.transcript import TurnTimeline

_PENDING_EDIT_FILENAME = "pending-certain-edits.json"
_PENDING_PATHS_FIELD = "paths"
_PENDING_RECORD_SHAPE_ERROR = "Pending certain edits must be an object"
_UTF8 = "utf-8"


class PendingEditEntry(TypedDict):
    """Validated paths waiting for one Antigravity result."""

    paths: list[str]


__all__ = [
    "declare_certain_edit",
    "declare_certain_timeline_edits",
    "hold_certain_edit",
    "settle_certain_edit",
]


def _validate_paths(paths: tuple[str, ...], checkout: Path) -> list[str]:
    """Resolve the recorded checkout context and discard paths outside it."""
    roots = resolve_invocation_roots(checkout)
    return quality_scope.validate_context_paths(list(paths), roots.repository_root, roots.context_root)


def _read_pending(transaction: FileTransaction) -> dict[str, PendingEditEntry]:
    """Read the Antigravity step-index map while its transaction lock is held."""
    raw = transaction.read_text(encoding=_UTF8)
    if not raw:
        return {}
    value: object = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(_PENDING_RECORD_SHAPE_ERROR)
    pending: dict[str, PendingEditEntry] = {}
    for step_id, entry in value.items():
        if not isinstance(step_id, str) or not isinstance(entry, dict):
            raise ValueError(_PENDING_RECORD_SHAPE_ERROR)
        paths = entry.get(_PENDING_PATHS_FIELD)
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            raise ValueError(_PENDING_RECORD_SHAPE_ERROR)
        pending[step_id] = {_PENDING_PATHS_FIELD: cast(list[str], paths)}
    return pending


def _write_pending(transaction: FileTransaction, pending: Mapping[str, PendingEditEntry]) -> None:
    """Replace the Antigravity step-index map atomically."""
    transaction.replace_text(json.dumps(dict(pending), sort_keys=True), creation_mode=0o600)


def declare_certain_edit(
    session_id: str,
    agent: AgentName,
    tool_name: str,
    tool_input: Mapping[str, object],
    checkout: Path,
) -> None:
    """Declare paths named by a successful hook event for a certain edit tool."""
    paths = certain_edit_paths(agent, tool_name, tool_input, workspace_root=checkout)
    safe_paths = _validate_paths(paths, checkout)
    if safe_paths:
        declare(session_id, safe_paths)


def hold_certain_edit(
    session_id: str,
    agent: AgentName,
    step_id: str,
    tool_name: str,
    tool_input: Mapping[str, object],
    checkout: Path,
) -> None:
    """Store validated paths until Antigravity reports the matching step outcome."""
    paths = certain_edit_paths(agent, tool_name, tool_input, workspace_root=checkout)
    safe_paths = _validate_paths(paths, checkout)
    if not safe_paths:
        return

    pending_path = session_tmp_dir(session_id) / _PENDING_EDIT_FILENAME
    with file_transaction(pending_path) as transaction:
        pending = _read_pending(transaction)
        pending[step_id] = {_PENDING_PATHS_FIELD: safe_paths}
        _write_pending(transaction, pending)


def settle_certain_edit(session_id: str, step_id: str, *, succeeded: bool) -> None:
    """Declare a held Antigravity edit only after its matching successful result."""
    pending_path = session_tmp_dir(session_id) / _PENDING_EDIT_FILENAME
    with file_transaction(pending_path) as transaction:
        pending = _read_pending(transaction)
        raw_entry = pending.pop(step_id, None)
        if raw_entry is None:
            return
        _write_pending(transaction, pending)

    if not succeeded:
        return
    declare(session_id, raw_entry[_PENDING_PATHS_FIELD])


def declare_certain_timeline_edits(
    session_id: str,
    agent: AgentName,
    timeline: TurnTimeline,
    checkout: Path,
) -> None:
    """Declare observed successful edit-tool calls found by the checkpoint backstop."""
    paths = extract_structured_paths_from_timeline(
        timeline,
        workspace_root=str(checkout),
        allowed_tools=CERTAIN_EDIT_TOOLS[agent],
    )
    safe_paths = _validate_paths(tuple(sorted(paths)), checkout)
    if safe_paths:
        declare(session_id, safe_paths)
