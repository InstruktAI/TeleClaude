"""Durable ledger persistence for session scoping."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

from instrukt_ai_logging import get_logger

from teleclaude.paths import SESSION_SCOPING_DIR

from ._types import WorkspaceKind, WorkspaceScopeLedger

logger = get_logger(__name__)

__all__ = [
    "load_workspace_ledger",
    "save_workspace_ledger",
]


class WorkspaceLedgerPayload(TypedDict):
    """Serialized workspace ledger payload."""

    workspace_root: str
    workspace_kind: str
    strategy: str
    agent: str
    seen_paths: list[str]
    last_updated: str


class SessionLedgerPayload(TypedDict):
    """Serialized per-session ledger document."""

    session_id: str
    workspaces: dict[str, WorkspaceLedgerPayload]


def _ledger_path(session_id: str) -> Path:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return SESSION_SCOPING_DIR / f"{digest}.json"


def _empty_session_document(session_id: str) -> SessionLedgerPayload:
    return {"session_id": session_id, "workspaces": {}}


def _workspace_payload_from_raw(raw_payload: object) -> WorkspaceLedgerPayload | None:
    if not isinstance(raw_payload, dict):
        return None

    workspace_root = raw_payload.get("workspace_root")
    workspace_kind = raw_payload.get("workspace_kind")
    strategy = raw_payload.get("strategy")
    agent = raw_payload.get("agent")
    last_updated = raw_payload.get("last_updated")
    raw_seen_paths = raw_payload.get("seen_paths", [])
    if not isinstance(raw_seen_paths, list) or not all(
        isinstance(value, str) for value in (workspace_root, workspace_kind, strategy, agent, last_updated)
    ):
        return None
    seen_paths = [path for path in raw_seen_paths if isinstance(path, str)]
    (
        workspace_root_str,
        workspace_kind_str,
        strategy_str,
        agent_str,
        last_updated_str,
    ) = cast(
        tuple[str, str, str, str, str],
        (workspace_root, workspace_kind, strategy, agent, last_updated),
    )
    payload: WorkspaceLedgerPayload = {
        "workspace_root": workspace_root_str,
        "workspace_kind": workspace_kind_str,
        "strategy": strategy_str,
        "agent": agent_str,
        "seen_paths": seen_paths,
        "last_updated": last_updated_str,
    }
    return payload


def _read_session_document(session_id: str) -> SessionLedgerPayload:
    path = _ledger_path(session_id)
    if not path.exists():
        return _empty_session_document(session_id)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Ledger file unreadable, resetting", path=str(path), session_id=session_id)
        return _empty_session_document(session_id)
    if not raw.strip():
        return _empty_session_document(session_id)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Ledger file corrupt, resetting", path=str(path), session_id=session_id)
        return _empty_session_document(session_id)
    if not isinstance(parsed, dict):
        return _empty_session_document(session_id)

    raw_workspaces = parsed.get("workspaces")
    workspaces: dict[str, WorkspaceLedgerPayload] = {}
    if isinstance(raw_workspaces, dict):
        for workspace_root, raw_payload in raw_workspaces.items():
            if not isinstance(workspace_root, str):
                continue
            workspace_payload = _workspace_payload_from_raw(raw_payload)
            if workspace_payload is not None:
                workspaces[workspace_root] = workspace_payload

    return {
        "session_id": session_id,
        "workspaces": workspaces,
    }


def _write_session_document(session_id: str, payload: SessionLedgerPayload) -> None:
    path = _ledger_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, indent=2, sort_keys=True)
        file_handle.flush()
        os.fsync(file_handle.fileno())
    os.replace(tmp_path, path)


def load_workspace_ledger(session_id: str, workspace_root: str) -> WorkspaceScopeLedger | None:
    """Load the persisted ledger entry for one session/workspace pair."""
    payload = _read_session_document(session_id)
    workspace_payload = payload["workspaces"].get(workspace_root)
    if workspace_payload is None:
        return None

    return WorkspaceScopeLedger(
        workspace_root=workspace_root,
        workspace_kind=cast(WorkspaceKind, workspace_payload["workspace_kind"]),
        strategy=workspace_payload["strategy"],
        agent=workspace_payload["agent"],
        seen_paths=tuple(workspace_payload["seen_paths"]),
        last_updated=workspace_payload["last_updated"],
    )


def save_workspace_ledger(session_id: str, ledger: WorkspaceScopeLedger) -> None:
    """Persist the ledger entry for one session/workspace pair."""
    payload = _read_session_document(session_id)
    payload["session_id"] = session_id
    payload["workspaces"][ledger.workspace_root] = {
        "workspace_root": ledger.workspace_root,
        "workspace_kind": ledger.workspace_kind,
        "strategy": ledger.strategy,
        "agent": ledger.agent,
        "seen_paths": list(ledger.seen_paths),
        "last_updated": ledger.last_updated,
    }
    _write_session_document(session_id, payload)


def current_timestamp() -> str:
    """Return an ISO 8601 UTC timestamp for ledger writes."""
    return datetime.now(UTC).isoformat()
