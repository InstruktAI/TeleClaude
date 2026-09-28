"""Read-only ownership query for dirty paths in the canonical checkout."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core.db import get_db
from teleclaude.core.models import Session
from teleclaude.quality.scope import DirtyPath, resolve_dirty_paths
from teleclaude.session_scoping import WorkspaceKind, live_declarations, resolve_workspace

logger = get_logger(__name__)

_QUERY_STARTED = "dirty_path_owners.query_started"
_QUERY_COMPLETED = "dirty_path_owners.query_completed"
_QUERY_FAILED = "dirty_path_owners.query_failed"


class DirtyPathOwnerPayload(TypedDict):
    """One live declaration owner printed by the CLI."""

    session_uuid: str
    job: str | None
    title: str


@dataclass(frozen=True)
class DirtyPathOwner:
    """Minimal session identity needed to identify a path's declarer."""

    session_uuid: str
    job: str | None
    title: str

    def as_json(self) -> DirtyPathOwnerPayload:
        """Return the documented CLI owner shape."""
        return DirtyPathOwnerPayload(
            session_uuid=self.session_uuid,
            job=self.job,
            title=self.title,
        )


@dataclass(frozen=True)
class DirtyPathOwnershipResult:
    """Complete ordered result for every dirty path in the canonical checkout."""

    owners: tuple[tuple[str, tuple[DirtyPathOwner, ...]], ...]

    def as_json(self) -> dict[str, list[DirtyPathOwnerPayload] | None]:
        """Return the documented path-keyed stdout payload."""
        return {
            path: [owner.as_json() for owner in path_owners] if path_owners else None
            for path, path_owners in self.owners
        }


async def resolve_dirty_path_owners(project_root: Path) -> DirtyPathOwnershipResult:
    """Resolve every dirty canonical-checkout path to its live declarers, if any."""
    dirty_paths = tuple(sorted(resolve_dirty_paths(project_root), key=lambda dirty_path: dirty_path.path))
    logger.info(_QUERY_STARTED, dirty_path_count=len(dirty_paths))
    sessions: list[Session] = []
    try:
        sessions = await _local_shared_checkout_sessions(project_root)
        session_declarations = await asyncio.gather(
            *(asyncio.to_thread(live_declarations, session.session_id) for session in sessions)
        )
        declarations_by_session = {
            session.session_id: frozenset(declaration.path for declaration in declarations)
            for session, declarations in zip(sessions, session_declarations, strict=True)
        }
        owners = _owners_for_dirty_paths(dirty_paths, sessions, declarations_by_session)
    except Exception:
        logger.error(
            _QUERY_FAILED,
            dirty_path_count=len(dirty_paths),
            session_count=len(sessions),
        )
        raise

    result = DirtyPathOwnershipResult(owners=owners)
    owner_count = sum(len(path_owners) for _, path_owners in owners)
    logger.info(
        _QUERY_COMPLETED,
        dirty_path_count=len(dirty_paths),
        session_count=len(sessions),
        owned_path_count=sum(bool(path_owners) for _, path_owners in owners),
        declaration_owner_count=owner_count,
    )
    return result


async def _local_shared_checkout_sessions(project_root: Path) -> list[Session]:
    """Select live local sessions whose working directory resolves to canonical main."""
    database = await get_db()
    sessions = await database.list_sessions(all_open=True)
    resolved_root = project_root.resolve()
    selected: list[Session] = []
    for session in sessions:
        if session.computer_name != config.computer.name or not session.project_path:
            continue
        working_path = Path(session.project_path)
        if session.subdir:
            working_path /= session.subdir
        workspace = resolve_workspace(str(working_path))
        if workspace.kind is not WorkspaceKind.GIT_SHARED or workspace.root is None:
            continue
        if Path(workspace.root).resolve() == resolved_root:
            selected.append(session)
    return selected


def _owners_for_dirty_paths(
    dirty_paths: tuple[DirtyPath, ...],
    sessions: list[Session],
    declarations_by_session: dict[str, frozenset[str]],
) -> tuple[tuple[str, tuple[DirtyPathOwner, ...]], ...]:
    """Join dirty repository paths to each matching live session declaration."""
    result: list[tuple[str, tuple[DirtyPathOwner, ...]]] = []
    for dirty_path in dirty_paths:
        path_owners = tuple(
            sorted(
                (
                    DirtyPathOwner(session_uuid=session.session_id, job=session.job, title=session.title)
                    for session in sessions
                    if dirty_path.path in declarations_by_session[session.session_id]
                ),
                key=lambda owner: owner.session_uuid,
            )
        )
        result.append((dirty_path.path, path_owners))
    return tuple(result)
