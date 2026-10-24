"""GitHub-backed workflow store that reuses the local implementation on a disposable copy."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from sqlalchemy import text
from sqlalchemy.orm import Session as SyncSession

from teleclaude.config.identity_schema import PersonEntry
from teleclaude.config.loader import github_actor_for_app_id
from teleclaude.config.project_models import TodoStoreBackend, TodoStoreConfig
from teleclaude.core.todos_db._adapter import TodosDb
from teleclaude.core.todos_db._github_questions import insert_awaiting_question
from teleclaude.core.todos_db._working_copy import (
    WorkingCopyField,
    WorkingCopyItemSnapshot,
    acquire_repository_writer,
    initialize_working_copy,
    item_bookkeeping,
    item_snapshot,
    mark_reflection_owed,
    repository_initialized,
    restore_item_snapshot,
    restore_project_record,
)
from teleclaude.core.todos_db_path import github_working_copy_path
from teleclaude.core.workflow_store.github import GitHubRepositoryIdentity, resolve_github_repository_identity
from teleclaude.core.workflow_store.github_io import GitHubMutationPacing, GitHubWorkflowIO
from teleclaude.core.workflow_store.github_push import GitHubWorkflowPush
from teleclaude.core.workflow_store.github_record import (
    CommentEnvelopeAction,
    CommentEnvelopeField,
    WorkflowField,
    render_comment_envelope,
)
from teleclaude.core.workflow_store.github_reflection import is_repository_work
from teleclaude.core.workflow_store.github_sync import GitHubWorkflowSync
from teleclaude.core.workflow_store.selection import selected_workflow_store_config
from teleclaude.core.workflow_store.types import StoreCapabilities
from teleclaude.types.github_binding import GitHubActorAssignment

if TYPE_CHECKING:
    from .store import WorkflowStore

_MISSING_APP = "GitHub workflow store requires todos.app to name a configured platform App"
_UNKNOWN_APP = "GitHub workflow store todos.app does not match a configured platform App"
_EMPTY = ""
_QUESTION_LINE_BREAK = "\n"
_MIGRATION_RECORD_ID = "github-store-switch:{}:{}"
_ITEM_ID_BY_SLUG = "SELECT CAST(id AS TEXT) FROM todo WHERE slug = :slug"
_instances: dict[str, GitHubWorkflowStore] = {}
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()
_new_instance_hook: Callable[[WorkflowStore, str], None] | None = None


class GitHubWorkflowStore(TodosDb):
    """Workflow port implementation over the local SQL model and GitHub system of record."""

    def __init__(
        self,
        path: Path,
        repository: GitHubRepositoryIdentity,
        assignment: GitHubActorAssignment,
    ) -> None:
        super().__init__(str(path))
        self._repository = repository
        self._assignment = assignment
        self._migration_lock = asyncio.Lock()
        self._io = GitHubWorkflowIO(repository, assignment)
        self._push = GitHubWorkflowPush(path, repository, assignment, self._io)
        self._sync = GitHubWorkflowSync(self, repository, assignment, self._io)
        self._push.set_conflict_refresh(self._sync.refresh)
        self.set_commit_callbacks(
            self._push.before_commit,
            self._push.after_commit,
            after_rollback=self._push.refresh_after_conflict,
        )

    async def restore_migration_item(self, snapshot: WorkingCopyItemSnapshot) -> None:
        """Publish one restored item through an async working-copy transaction."""
        async with self._session() as session:
            async with session.begin():
                await session.run_sync(acquire_repository_writer)
                await session.run_sync(
                    lambda sync_session: restore_item_snapshot(sync_session, snapshot, capture_changes=True)
                )

    @asynccontextmanager
    async def paced_mutations(self) -> AsyncIterator[GitHubMutationPacing]:
        """Expose the adapter's scoped mutation pacing to the migration owner."""
        async with self._migration_lock:
            async with self._io.paced_mutations() as pacing:
                yield pacing

    async def restore_migration_project_records(self, records: tuple[tuple[str, Mapping[str, object]], ...]) -> None:
        """Publish one bounded project-record batch through the existing ledger path."""
        async with self._session() as session:
            async with session.begin():
                await session.run_sync(acquire_repository_writer)
                await session.run_sync(
                    lambda sync_session: [
                        restore_project_record(
                            sync_session,
                            table,
                            row,
                            _MIGRATION_RECORD_ID.format(table, row[WorkingCopyField.ID]),
                            capture_changes=True,
                        )
                        for table, row in records
                    ]
                )

    @property
    def capabilities(self) -> StoreCapabilities:
        """Expose every workflow operation without the local incremental transfer capability."""
        return StoreCapabilities(
            local_items=True,
            claims=True,
            phases=True,
            artifacts=True,
            revision_stamps=True,
            trail=True,
            delivery_candidates=True,
            incremental_replica_transfer=False,
        )

    async def initialize_github(self) -> None:
        """Open the local substrate and install its working-copy triggers."""
        await self.initialize()
        initialize_working_copy(self.db_path)

    def initialize_github_sync(self) -> None:
        """Synchronous sibling for CLI and integration processes."""
        self.initialize_sync()
        initialize_working_copy(self.db_path)

    async def rebuild(self) -> None:
        """Populate a newly created working copy from the repository before serving it."""
        await self._sync.rebuild()

    async def refresh_working_copy(self) -> int:
        """Adopt committed changes made by another computer and repair owed reflections."""
        return await self._sync.refresh()

    async def surface_question(
        self,
        slug: str,
        session_id: str,
        role: str | None,
        message: str,
        session_link: str | None,
        recipients: tuple[str | PersonEntry, ...],
    ) -> None:
        """Append a delivered person message as an issue question and track its assignment."""
        async with self._session() as session:
            async with session.begin():
                await session.run_sync(acquire_repository_writer)

                def read_item(
                    sync_session: SyncSession,
                ) -> tuple[str, WorkingCopyItemSnapshot | None, Mapping[str, object] | None] | None:
                    item_id = sync_session.execute(text(_ITEM_ID_BY_SLUG), {"slug": slug}).scalar_one_or_none()
                    if item_id is None:
                        return None
                    normalized_id = str(item_id)
                    return (
                        normalized_id,
                        item_snapshot(sync_session, normalized_id),
                        item_bookkeeping(sync_session, normalized_id),
                    )

                found = await session.run_sync(read_item)
                if found is None:
                    return
                item_id, snapshot_value, bookkeeping_value = found
                if snapshot_value is None or bookkeeping_value is None:
                    return
                snapshot = snapshot_value
                bookkeeping = bookkeeping_value
                if not is_repository_work(snapshot.state):
                    return
                issue_number_value = bookkeeping.get(WorkflowField.ISSUE_NUMBER)
                if not isinstance(issue_number_value, int):
                    return
                state_value = snapshot.state.get(WorkflowField.STATE) if snapshot.state is not None else None
                try:
                    state = json.loads(state_value) if isinstance(state_value, str) else {}
                except json.JSONDecodeError:
                    state = {}
                phase = state.get(WorkflowField.LIFECYCLE_PHASE) if isinstance(state, dict) else None
                if not isinstance(phase, str):
                    return
                recipient_slug_list: list[str] = []
                for recipient in recipients:
                    if isinstance(recipient, str):
                        recipient_slug_list.append(recipient)
                    elif recipient.slug:
                        recipient_slug_list.append(recipient.slug)
                recipient_slugs = tuple(dict.fromkeys(recipient_slug_list))
                asked_at = datetime.now(UTC).isoformat()
                envelope = render_comment_envelope(
                    (
                        (CommentEnvelopeField.SESSION, session_id),
                        (CommentEnvelopeField.ROLE, role),
                        (CommentEnvelopeField.ACTION, CommentEnvelopeAction.QUESTION),
                    )
                )
                body = (
                    envelope
                    + _QUESTION_LINE_BREAK
                    + message
                    + (_QUESTION_LINE_BREAK + session_link if session_link else _EMPTY)
                )

                def record_question(sync_session: SyncSession) -> None:
                    insert_awaiting_question(
                        sync_session,
                        item_id=item_id,
                        session_id=session_id,
                        asked_at=asked_at,
                        phase=phase,
                        recipient_slugs=recipient_slugs,
                    )
                    mark_reflection_owed(sync_session, item_id)

                await session.run_sync(record_question)
                await self._io.async_create_comment(issue_number_value, body)
        await self.refresh_working_copy()

    def rebuild_sync(self) -> None:
        self._sync.rebuild_sync()


def set_github_workflow_store_hook(hook: Callable[[WorkflowStore, str], None] | None) -> None:
    """Attach the shared daemon mutation hook to newly created GitHub stores."""
    global _new_instance_hook
    _new_instance_hook = hook


async def get_github_workflow_store(project_root_or_cwd: str | Path) -> WorkflowStore:
    """Resolve one cached GitHub store and rebuild its first working copy."""
    root, identity, assignment = _resolve_selection(project_root_or_cwd)
    key = str(github_working_copy_path(root))
    lock = _lock_for(key)
    await asyncio.to_thread(lock.acquire)
    try:
        existing = _instances.get(key)
        if existing is not None:
            return existing
        path = Path(key)
        existed = path.is_file()
        store = GitHubWorkflowStore(path, identity, assignment)
        await store.initialize_github()
        if not existed or not repository_initialized(path):
            await store.rebuild()
        if _new_instance_hook is not None:
            _new_instance_hook(store, str(root))
        _instances[key] = store
        return store
    finally:
        lock.release()


def get_github_workflow_store_sync(project_root_or_cwd: str | Path) -> WorkflowStore:
    """Synchronous resolver sharing the canonical-root cache with async callers."""
    root, identity, assignment = _resolve_selection(project_root_or_cwd)
    key = str(github_working_copy_path(root))
    lock = _lock_for(key)
    lock.acquire()
    try:
        existing = _instances.get(key)
        if existing is not None:
            return existing
        path = Path(key)
        existed = path.is_file()
        store = GitHubWorkflowStore(path, identity, assignment)
        store.initialize_github_sync()
        if not existed or not repository_initialized(path):
            store.rebuild_sync()
        if _new_instance_hook is not None:
            _new_instance_hook(store, str(root))
        _instances[key] = store
        return store
    finally:
        lock.release()


async def close_github_workflow_stores() -> None:
    """Close every cached GitHub working copy."""
    with _guard:
        stores = list(_instances.values())
        _instances.clear()
        _locks.clear()
    for store in stores:
        await store.close()


async def refresh_github_workflow_store(project_root_or_cwd: str | Path) -> int:
    """Refresh the selected project's shared GitHub working copy."""
    store = await get_github_workflow_store(project_root_or_cwd)
    return await cast(GitHubWorkflowStore, store).refresh_working_copy()


async def surface_github_question(
    project_root: str | Path,
    slug: str,
    session_id: str,
    role: str | None,
    message: str,
    session_link: str | None,
    recipients: tuple[str | PersonEntry, ...],
) -> None:
    """Hand one delivered person message to the selected GitHub issue projection."""
    root = Path(project_root)
    if selected_workflow_store_config(root).store is not TodoStoreBackend.GITHUB:
        return
    store = cast(GitHubWorkflowStore, await get_github_workflow_store(root))
    await store.surface_question(slug, session_id, role, message, session_link, recipients)


def _resolve_selection(
    project_root_or_cwd: str | Path,
) -> tuple[Path, GitHubRepositoryIdentity, GitHubActorAssignment]:
    identity = resolve_github_repository_identity(project_root_or_cwd)
    selection: TodoStoreConfig = selected_workflow_store_config(identity.project_path)
    if selection.app is None:
        raise ValueError(_MISSING_APP)
    assignment = github_actor_for_app_id(selection.app)
    if assignment is None:
        raise ValueError(_UNKNOWN_APP)
    return identity.project_path, identity, assignment


def _lock_for(key: str) -> threading.Lock:
    with _guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock
