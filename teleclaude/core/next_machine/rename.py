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
    _run_git_cmd,
    delete_old_remote_slug_ref,
    move_todo_slug_surfaces,
    rollback_todo_slug_surfaces,
)
from teleclaude.core.operation_caller_identity import get_caller_session_id
from teleclaude.core.todos_db import TodosDb, get_todos_db
from teleclaude.docs_reconcile import (
    SnippetDeliveredByRewriteResult,
    _delivered_by,
    _iter_snippet_files,
    _split_frontmatter,
    rewrite_delivered_by_slug,
)
from teleclaude.git import InvalidGitRepositoryError, Repo
from teleclaude.project_root import resolve_state_root
from teleclaude.slug import validate_slug

logger = get_logger(__name__)


class DeliveredByRenameFailure(RuntimeError):
    """Failure in the post-DB delivered_by rewrite/commit leg."""

    def __init__(self, message: str, paths: list[Path]) -> None:
        super().__init__(message)
        self.paths = tuple(paths)


def _would_mutate_paths(project_root: Path, old_slug: str) -> list[Path]:
    """Return snippet paths whose delivered_by frontmatter contains the old slug."""
    paths: list[Path] = []
    for snippet_path in _iter_snippet_files(project_root):
        content = snippet_path.read_text(encoding="utf-8")
        parsed = _split_frontmatter(content)
        if parsed is None:
            continue
        metadata, _body = parsed
        if old_slug in _delivered_by(metadata):
            paths.append(snippet_path)
    return paths


def _pathspecs(project_root: Path, paths: list[Path]) -> list[str]:
    return [path.relative_to(project_root).as_posix() for path in paths]


def _check_rename_preconditions(project_root: Path, old_slug: str) -> str | None:
    """Return a refusal reason when rename snippet mutation cannot run safely."""
    try:
        rc, _, _stderr = _run_git_cmd(["rev-parse", "--git-dir"], cwd=str(project_root), timeout=5)
    except InvalidGitRepositoryError:
        rc = 1
    if rc != 0:
        return "project root is not a git repository"

    candidate_paths = _would_mutate_paths(project_root, old_slug)
    if not candidate_paths:
        return None

    rc, stdout, stderr = _run_git_cmd(
        ["status", "--porcelain", "--", *_pathspecs(project_root, candidate_paths)],
        cwd=str(project_root),
        timeout=5,
    )
    if rc != 0:
        return f"git status failed: {stderr.strip()}"
    if stdout.strip():
        first_dirty = stdout.splitlines()[0]
        path = first_dirty[3:] if len(first_dirty) > 3 else first_dirty
        return f"dirty working tree on snippet path: {path}"
    return None


def _rewrite_and_commit_delivered_by(
    project_root: Path,
    old_slug: str,
    new_slug: str,
) -> list[SnippetDeliveredByRewriteResult]:
    """Rewrite delivered_by references and commit exactly the mutated snippet paths."""
    candidate_paths = _would_mutate_paths(project_root, old_slug)
    if not candidate_paths:
        return []

    rc, stdout, stderr = _run_git_cmd(
        ["status", "--porcelain", "--", *_pathspecs(project_root, candidate_paths)],
        cwd=str(project_root),
        timeout=5,
    )
    if rc != 0:
        msg = f"git status failed before delivered_by rename: {stderr.strip()}"
        raise DeliveredByRenameFailure(msg, candidate_paths)
    if stdout.strip():
        first_dirty = stdout.splitlines()[0]
        path = first_dirty[3:] if len(first_dirty) > 3 else first_dirty
        msg = f"dirty working tree changed during delivered_by rename: {path}"
        raise DeliveredByRenameFailure(msg, candidate_paths)

    try:
        rewrites = rewrite_delivered_by_slug(project_root, old_slug, new_slug)
    except Exception as exc:
        msg = f"delivered_by rewrite failed: {exc}"
        raise DeliveredByRenameFailure(msg, candidate_paths) from exc
    if not rewrites:
        return []

    pathspecs = _pathspecs(project_root, [rewrite.path for rewrite in rewrites])
    rc, _, stderr = _run_git_cmd(["add", "--", *pathspecs], cwd=str(project_root), timeout=10)
    if rc != 0:
        msg = f"git add failed for delivered_by rename: {stderr.strip()}"
        raise DeliveredByRenameFailure(msg, candidate_paths)

    message = f"refactor(workflow): rename {old_slug}->{new_slug}; substitute delivered_by in {len(rewrites)} snippets"
    rc, _, stderr = _run_git_cmd(["commit", "-m", message, "--", *pathspecs], cwd=str(project_root), timeout=30)
    if rc != 0:
        msg = f"git commit failed for delivered_by rename: {stderr.strip()}"
        raise DeliveredByRenameFailure(msg, candidate_paths)
    return rewrites


def _restore_snippet_paths_from_head(project_root: Path, paths: tuple[Path, ...]) -> None:
    repo = Repo(str(project_root))
    for path in paths:
        pathspec = path.relative_to(project_root).as_posix()
        blob = repo.commit("HEAD").tree / pathspec
        path.write_bytes(blob.data_stream.read())


def _sync_snippet_index_to_head(project_root: Path, paths: tuple[Path, ...]) -> None:
    if not paths:
        return
    rc, _, stderr = _run_git_cmd(
        ["add", "--", *_pathspecs(project_root, list(paths))], cwd=str(project_root), timeout=10
    )
    if rc != 0:
        msg = f"git add failed while restoring delivered_by rename index: {stderr.strip()}"
        raise RuntimeError(msg)


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


async def _compensate_todo_db_rename(todos_db: TodosDb, old_slug: str, new_slug: str) -> None:
    async with todos_db._session() as session:  # pylint: disable=protected-access
        async with session.begin():
            if not await todos_db.rename_state_slug(new_slug, old_slug, session=session):
                raise RuntimeError(f"state compensation failed for {new_slug!r}")
            if not await todos_db.rename_artifacts_slug(new_slug, old_slug, session=session):
                raise RuntimeError(f"artifact compensation failed for {new_slug!r}")
            if not await todos_db.rename_roadmap_slug(new_slug, old_slug, session=session):
                raise RuntimeError(f"roadmap compensation failed for {new_slug!r}")


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

    if not await todos_db.slug_in_roadmap(old_slug):
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

    precondition_error = _check_rename_preconditions(project_root, old_slug)
    if precondition_error is not None:
        return _refusal(precondition_error)

    snippet_snapshot = _snapshot_snippet_bytes(project_root)
    moves: list[TodoSlugSurfaceMove] = []
    snippet_count = 0
    db_committed = False
    try:
        moves = move_todo_slug_surfaces(project_root_str, old_slug, new_slug)

        async with todos_db._session() as session:  # pylint: disable=protected-access
            async with session.begin():
                if not await todos_db.rename_state_slug(old_slug, new_slug, session=session):
                    raise RuntimeError(f"state rename failed for {old_slug!r}")
                if not await todos_db.rename_artifacts_slug(old_slug, new_slug, session=session):
                    raise RuntimeError(f"artifact rename failed for {old_slug!r}")
                if not await todos_db.rename_roadmap_slug(old_slug, new_slug, session=session):
                    raise RuntimeError(f"roadmap rename failed for {old_slug!r}")
        db_committed = True
        snippet_rewrites = _rewrite_and_commit_delivered_by(project_root, old_slug, new_slug)
        snippet_count = len(snippet_rewrites)
    except DeliveredByRenameFailure as exc:
        cleanup_error: Exception | None = None
        try:
            _restore_snippet_paths_from_head(project_root, exc.paths)
            _sync_snippet_index_to_head(project_root, exc.paths)
        except Exception as restore_exc:
            cleanup_error = restore_exc
        try:
            rollback_todo_slug_surfaces(project_root_str, moves)
        except Exception as rollback_exc:
            cleanup_error = rollback_exc if cleanup_error is None else cleanup_error
        if db_committed:
            await _compensate_todo_db_rename(todos_db, old_slug, new_slug)
        if cleanup_error is not None:
            msg = "post-db delivered_by rename cleanup failed after DB compensation"
            raise RuntimeError(msg) from cleanup_error
        return _refusal(f"post-db failure (compensated): {exc}")
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
