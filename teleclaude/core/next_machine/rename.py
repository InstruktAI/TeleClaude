"""Receipt-backed todo rename engine."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from instrukt_ai_logging import get_logger

from teleclaude.constants import CacheEvent
from teleclaude.core.db import Db
from teleclaude.core.next_machine.delivery import (
    TodoSlugSurfaceMove,
    delete_old_remote_slug_ref,
    move_todo_slug_surfaces,
    rollback_todo_slug_surfaces,
)
from teleclaude.core.operation_caller_identity import get_caller_session_id
from teleclaude.core.todos_db import get_todos_db
from teleclaude.docs_reconcile import _iter_snippet_files, rewrite_delivered_by_slug
from teleclaude.project_root import resolve_state_root
from teleclaude.slug import validate_slug

logger = get_logger(__name__)


def _snapshot_snippet_bytes(project_root: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in _iter_snippet_files(project_root)}


def _restore_snippet_bytes(snapshot: Mapping[Path, bytes]) -> None:
    for path, content in snapshot.items():
        path.write_bytes(content)


def _moved_surfaces(*, snippet_count: int, moves: list[TodoSlugSurfaceMove]) -> list[str]:
    surfaces = ["todos.db"]
    if snippet_count:
        surfaces.append(f"delivered_by:{snippet_count}")
    surfaces.extend(move.surface for move in moves if move.surface != "remote_branch")
    if any(move.surface == "remote_branch" for move in moves):
        surfaces.append("remote_branch")
    return surfaces


def _summary(old_slug: str, new_slug: str, *, surfaces: list[str]) -> str:
    return f"renamed {old_slug}->{new_slug} ({', '.join(surfaces)})"


def _refusal(message: str) -> str:
    return f"error: {message}"


async def _renamed_by_principal(db: Db) -> str:
    caller_session_id = get_caller_session_id()
    if not caller_session_id:
        return ""
    session = await db.get_session(caller_session_id)
    if session is None:
        return caller_session_id
    principal = getattr(session, "principal", None)
    return principal if isinstance(principal, str) and principal else caller_session_id


async def _blocking_reason(
    db: Db,
    *,
    old_slug: str,
    cwd: str,
    current_operation_id: str | None,
) -> str | None:
    operations = await db.find_nonterminal_operations_bound_to_todo(
        old_slug=old_slug,
        cwd=cwd,
        exclude_operation_id=current_operation_id,
    )
    if operations:
        operation_ids = ", ".join(operation.operation_id for operation in operations)
        return f"cannot rename {old_slug}: non-terminal operation is bound to it ({operation_ids})"

    sessions = await db.find_open_sessions_bound_to_todo(old_slug=old_slug, cwd=cwd)
    if sessions:
        session_ids = ", ".join(session.session_id for session in sessions)
        return f"cannot rename {old_slug}: open session is bound to it ({session_ids})"
    return None


async def _rewrite_daemon_refs(db: Db, *, old_slug: str, new_slug: str, cwd: str) -> None:
    try:
        await db.rewrite_operation_todo_refs(old_slug=old_slug, new_slug=new_slug)
        await db.rewrite_session_todo_refs(old_slug=old_slug, new_slug=new_slug, cwd=cwd)
    except Exception as exc:  # pragma: no cover - post-commit reconciliation is best effort
        logger.warning("post-rename daemon reference reconciliation failed: %s", exc)


async def execute_todo_rename(
    db: Db,
    old_slug: str,
    new_slug: str,
    cwd: str,
    *,
    current_operation_id: str | None = None,
) -> str:
    """Rename a todo across durable and physical slug-bearing surfaces."""
    try:
        validate_slug(old_slug)
        validate_slug(new_slug)
    except ValueError as exc:
        return _refusal(str(exc))
    if old_slug == new_slug:
        return _refusal("old and new slug must differ")

    project_root = resolve_state_root(cwd)
    project_root_str = str(project_root)
    todos_db = await get_todos_db(project_root)

    if not await todos_db.slug_in_todo(old_slug):
        return _refusal(f"todo {old_slug!r} was not found")
    if await todos_db.slug_conflicts_non_removed(new_slug):
        return _refusal(f"new slug {new_slug!r} is already held by a non-removed todo")

    blocking_reason = await _blocking_reason(
        db,
        old_slug=old_slug,
        cwd=project_root_str,
        current_operation_id=current_operation_id,
    )
    if blocking_reason is not None:
        return _refusal(blocking_reason)

    snippet_snapshot = _snapshot_snippet_bytes(project_root)
    moves: list[TodoSlugSurfaceMove] = []
    snippet_count = 0
    try:
        moves = move_todo_slug_surfaces(project_root_str, old_slug, new_slug)
        snippet_rewrites = rewrite_delivered_by_slug(project_root, old_slug, new_slug)
        snippet_count = len(snippet_rewrites)

        async with todos_db._session() as session:  # pylint: disable=protected-access
            async with session.begin():
                if not await todos_db.rename_state_slug(old_slug, new_slug, session=session):
                    raise RuntimeError(f"state rename failed for {old_slug!r}")
                if not await todos_db.rename_artifacts_slug(old_slug, new_slug, session=session):
                    raise RuntimeError(f"artifact rename failed for {old_slug!r}")
                if not await todos_db.rename_todo_slug(old_slug, new_slug, session=session):
                    raise RuntimeError(f"todo rename failed for {old_slug!r}")
    except Exception:
        _restore_snippet_bytes(snippet_snapshot)
        rollback_todo_slug_surfaces(project_root_str, moves)
        raise

    await _rewrite_daemon_refs(db, old_slug=old_slug, new_slug=new_slug, cwd=project_root_str)
    if any(move.surface == "remote_branch" for move in moves):
        delete_old_remote_slug_ref(project_root_str, old_slug)

    surfaces_moved = _moved_surfaces(snippet_count=snippet_count, moves=moves)
    renamed_at = datetime.now(UTC).isoformat()
    event_payload = {
        "old_slug": old_slug,
        "new_slug": new_slug,
        "renamed_at": renamed_at,
        "renamed_by_principal": await _renamed_by_principal(db),
        "surfaces_moved": surfaces_moved,
    }
    todos_db.on_committed(CacheEvent.TODO_RENAMED.value, cast(Mapping[str, object], event_payload))

    logger.info("Renamed todo %s -> %s", old_slug, new_slug)
    return _summary(old_slug, new_slug, surfaces=surfaces_moved)
