"""Batch ownership query for an already-classified dirty path set."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core.db import get_db
from teleclaude.core.models import Session
from teleclaude.git import GitCommandError, Repo
from teleclaude.quality.scope import resolve_dirty_paths
from teleclaude.session_identity import get_session_id
from teleclaude.session_scoping import (
    AttributionSignal,
    SessionAttributionResult,
    TouchEvidence,
    resolve_session_attribution,
)

logger = get_logger(__name__)

_ERROR_EMPTY_BATCH = "At least one project-relative dirty path is required."
_ERROR_ABSOLUTE_PATH = "Ownership paths must be project-relative: {path}"
_ERROR_INVALID_PATH = "Ownership path is invalid: {path}"
_ERROR_DUPLICATE_PATH = "Ownership paths must be unique after normalization: {path}"
_ERROR_NOT_DIRTY = "Ownership path is not dirty in the captured workspace set: {path}"
_ERROR_GIT_HISTORY = "Failed to resolve last committed boundary for ownership path: {path}"
_GIT_LOG_FORMAT = "--format=%cI"
_GIT_PATH_SEPARATOR = "--"
_QUERY_STARTED = "dirty_path_owners.query_started"
_QUERY_COMPLETED = "dirty_path_owners.query_completed"
_QUERY_FAILED = "dirty_path_owners.query_failed"
_EMPTY_CALLER_SESSION = ""


@dataclass(frozen=True)
class DirtyPathOwner:
    """Minimal session identity needed to coordinate a path's owner."""

    session_uuid: str
    job: str | None
    title: str

    def as_json(self) -> dict[str, str | None]:
        """Return the documented CLI owner shape."""
        return {"session_uuid": self.session_uuid, "job": self.job, "title": self.title}


@dataclass(frozen=True)
class DirtyPathOwnershipResult:
    """Complete ordered batch result plus the non-identifying safety signal."""

    owners: tuple[tuple[str, DirtyPathOwner | None], ...]
    undetermined_session_count: int
    query_id: str

    def as_json(self) -> dict[str, dict[str, str | None] | None]:
        """Return only the documented path-keyed stdout payload."""
        return {path: owner.as_json() if owner is not None else None for path, owner in self.owners}


async def resolve_dirty_path_owners(
    project_root: Path,
    requested_paths: list[str],
) -> DirtyPathOwnershipResult:
    """Resolve the earliest still-uncommitted live claimant for every requested path."""
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
        boundaries = _resolve_commit_boundaries(project_root, normalized_paths)
        sessions = await _local_project_sessions(project_root)
        attributions = await asyncio.gather(
            *(
                asyncio.to_thread(resolve_session_attribution, session, workspace_root=str(project_root))
                for session in sessions
            )
        )
        owners = _select_owners(normalized_paths, boundaries, sessions, attributions)
        undetermined_count = sum(attribution.signal is AttributionSignal.UNDETERMINED for attribution in attributions)
    except Exception:
        logger.exception(_QUERY_FAILED, query_id=query_id, caller_session_id=caller_session_id)
        raise
    result = DirtyPathOwnershipResult(
        owners=owners,
        undetermined_session_count=undetermined_count,
        query_id=query_id,
    )
    logger.info(
        _QUERY_COMPLETED,
        query_id=query_id,
        caller_session_id=caller_session_id,
        requested_count=len(normalized_paths),
        captured_session_count=len(sessions),
        undetermined_session_count=undetermined_count,
        owned_count=sum(owner is not None for _, owner in owners),
        null_count=sum(owner is None for _, owner in owners),
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


def _resolve_commit_boundaries(project_root: Path, paths: tuple[str, ...]) -> dict[str, datetime | None]:
    repo = Repo(str(project_root))
    return {path: _last_commit_at(repo, path) for path in paths}


def _last_commit_at(repo: Repo, path: str) -> datetime | None:
    try:
        timestamp = repo.git.log("-1", _GIT_LOG_FORMAT, _GIT_PATH_SEPARATOR, path).strip()
    except GitCommandError as exc:
        raise RuntimeError(_ERROR_GIT_HISTORY.format(path=path)) from exc
    if not timestamp:
        return None
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None:
        raise RuntimeError(_ERROR_GIT_HISTORY.format(path=path))
    return parsed.astimezone(UTC)


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
    boundaries: dict[str, datetime | None],
    sessions: list[Session],
    attributions: list[SessionAttributionResult],
) -> tuple[tuple[str, DirtyPathOwner | None], ...]:
    candidates: dict[str, list[tuple[datetime, str, DirtyPathOwner]]] = {path: [] for path in paths}
    for session, attribution in zip(sessions, attributions, strict=True):
        for touch in attribution.touches:
            _add_surviving_candidate(candidates, boundaries, session, touch)
    selected: list[tuple[str, DirtyPathOwner | None]] = []
    for path in paths:
        path_candidates = candidates[path]
        owner = min(path_candidates, default=None, key=lambda candidate: (candidate[0], candidate[1]))
        selected.append((path, owner[2] if owner is not None else None))
    return tuple(selected)


def _add_surviving_candidate(
    candidates: dict[str, list[tuple[datetime, str, DirtyPathOwner]]],
    boundaries: dict[str, datetime | None],
    session: Session,
    touch: TouchEvidence,
) -> None:
    path_candidates = candidates.get(touch.path)
    if path_candidates is None:
        return
    boundary = boundaries[touch.path]
    if boundary is not None and touch.touched_at <= boundary:
        return
    path_candidates.append(
        (
            touch.touched_at,
            session.session_id,
            DirtyPathOwner(session_uuid=session.session_id, job=session.job, title=session.title),
        )
    )
