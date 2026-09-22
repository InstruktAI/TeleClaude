"""Batch ownership query for an already-classified dirty path set."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core.agents import AgentName, get_default_agent
from teleclaude.core.db import get_db
from teleclaude.core.models import Session
from teleclaude.quality.scope import resolve_dirty_paths
from teleclaude.session_identity import get_session_id
from teleclaude.session_scoping import resolve_scoped_paths

logger = get_logger(__name__)

_ERROR_EMPTY_BATCH = "At least one project-relative dirty path is required."
_ERROR_ABSOLUTE_PATH = "Ownership paths must be project-relative: {path}"
_ERROR_INVALID_PATH = "Ownership path is invalid: {path}"
_ERROR_DUPLICATE_PATH = "Ownership paths must be unique after normalization: {path}"
_ERROR_NOT_DIRTY = "Ownership path is not dirty in the captured workspace set: {path}"
_QUERY_STARTED = "dirty_path_owners.query_started"
_QUERY_COMPLETED = "dirty_path_owners.query_completed"
_QUERY_FAILED = "dirty_path_owners.query_failed"
_EMPTY_CALLER_SESSION = ""


@dataclass(frozen=True)
class DirtyPathOwner:
    """Minimal session identity needed to identify a path's declarer."""

    session_uuid: str
    job: str | None
    title: str

    def as_json(self) -> dict[str, str | None]:
        """Return the documented CLI owner shape."""
        return {"session_uuid": self.session_uuid, "job": self.job, "title": self.title}


@dataclass(frozen=True)
class DirtyPathOwnershipResult:
    """Complete ordered batch result of every live session that declared each path."""

    owners: tuple[tuple[str, tuple[DirtyPathOwner, ...]], ...]
    query_id: str

    def as_json(self) -> dict[str, list[dict[str, str | None]] | None]:
        """Return only the documented path-keyed stdout payload."""
        return {
            path: [declarer.as_json() for declarer in declarers] if declarers else None
            for path, declarers in self.owners
        }


async def resolve_dirty_path_owners(
    project_root: Path,
    requested_paths: list[str],
) -> DirtyPathOwnershipResult:
    """Resolve every live session that has declared each requested dirty path.

    Declarations are read, never inferred: no transcript is inspected for
    file-edit evidence and no commit authorship is consulted. Several live
    sessions may declare the same path; each is reported, with no tiebreak.
    """
    query_id = str(uuid4())
    caller_session_id = get_session_id() or _EMPTY_CALLER_SESSION
    normalized_paths = _normalize_requested_paths(project_root, requested_paths)
    logger.info(
        _QUERY_STARTED,
        query_id=query_id,
        caller_session_id=caller_session_id,
        requested_count=len(normalized_paths),
    )
    try:
        dirty_paths = resolve_dirty_paths(project_root)
        dirty_path_set = {dirty.path for dirty in dirty_paths}
        _require_dirty_paths(normalized_paths, dirty_path_set)
        sessions = await _local_project_sessions(project_root)
        declared_sets = await asyncio.gather(
            *(asyncio.to_thread(_resolve_session_declared_paths, session, project_root) for session in sessions)
        )
        owners = _select_owners(normalized_paths, sessions, declared_sets)
    except Exception:
        logger.exception(_QUERY_FAILED, query_id=query_id, caller_session_id=caller_session_id)
        raise
    result = DirtyPathOwnershipResult(owners=owners, query_id=query_id)
    logger.info(
        _QUERY_COMPLETED,
        query_id=query_id,
        caller_session_id=caller_session_id,
        requested_count=len(normalized_paths),
        captured_session_count=len(sessions),
        owned_count=sum(bool(declarers) for _, declarers in owners),
        null_count=sum(not declarers for _, declarers in owners),
    )
    return result


def _normalize_requested_paths(project_root: Path, requested_paths: list[str]) -> tuple[str, ...]:
    if not requested_paths:
        raise ValueError(_ERROR_EMPTY_BATCH)
    root = project_root.resolve()
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_path in requested_paths:
        candidate = Path(raw_path)
        if candidate.is_absolute():
            raise ValueError(_ERROR_ABSOLUTE_PATH.format(path=raw_path))
        if raw_path.startswith("-"):
            raise ValueError(_ERROR_INVALID_PATH.format(path=raw_path))
        resolved = (root / candidate).resolve()
        try:
            path = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError(_ERROR_INVALID_PATH.format(path=raw_path)) from exc
        if path in {"", "."} or path.startswith("-"):
            raise ValueError(_ERROR_INVALID_PATH.format(path=raw_path))
        if path in seen:
            raise ValueError(_ERROR_DUPLICATE_PATH.format(path=raw_path))
        seen.add(path)
        normalized.append(path)
    return tuple(normalized)


def _require_dirty_paths(requested_paths: tuple[str, ...], dirty_path_set: set[str]) -> None:
    for path in requested_paths:
        if path not in dirty_path_set:
            raise ValueError(_ERROR_NOT_DIRTY.format(path=path))


def _resolve_session_declared_paths(session: Session, project_root: Path) -> frozenset[str]:
    """Resolve one live session's declared paths from its own transcript record."""
    agent_raw = (session.active_agent or "").strip()
    try:
        agent = AgentName.from_str(agent_raw) if agent_raw else AgentName.from_str(get_default_agent())
    except ValueError:
        return frozenset()
    scoped = resolve_scoped_paths(
        session_id=session.session_id,
        workspace_root=str(project_root),
        agent_name=agent.value,
        scope_mode="session_dirty",
        transcript_path=session.native_log_file or None,
        native_session_id=session.native_session_id,
        transcript_files=session.transcript_files,
    )
    return frozenset(scoped.declared_paths)


async def _local_project_sessions(project_root: Path) -> list[Session]:
    db = await get_db()
    sessions = await db.list_sessions(all_open=True)
    resolved_root = project_root.resolve()
    return [
        session
        for session in sessions
        if session.computer_name == config.computer.name
        and session.project_path is not None
        and Path(session.project_path).resolve() == resolved_root
    ]


def _select_owners(
    paths: tuple[str, ...],
    sessions: list[Session],
    declared_sets: list[frozenset[str]],
) -> tuple[tuple[str, tuple[DirtyPathOwner, ...]], ...]:
    selected: list[tuple[str, tuple[DirtyPathOwner, ...]]] = []
    for path in paths:
        declarers = tuple(
            DirtyPathOwner(session_uuid=session.session_id, job=session.job, title=session.title)
            for session, declared in zip(sessions, declared_sets, strict=True)
            if path in declared
        )
        selected.append((path, declarers))
    return tuple(selected)
