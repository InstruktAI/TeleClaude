"""GitHub-backed workflow store that reuses the local implementation on a disposable copy."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, cast

from teleclaude.config.loader import github_actor_for_app_id
from teleclaude.config.project_models import TodoStoreConfig
from teleclaude.core.todos_db._adapter import TodosDb
from teleclaude.core.todos_db._working_copy import (
    WorkingCopyField,
    WorkingCopyItemSnapshot,
    acquire_repository_writer,
    initialize_working_copy,
    repository_initialized,
    restore_item_snapshot,
    restore_project_record,
)
from teleclaude.core.todos_db_path import github_working_copy_path
from teleclaude.core.workflow_store.github import GitHubRepositoryIdentity, resolve_github_repository_identity
from teleclaude.core.workflow_store.github_io import GitHubMutationPacing, GitHubWorkflowIO
from teleclaude.core.workflow_store.github_push import GitHubWorkflowPush
from teleclaude.core.workflow_store.github_sync import GitHubWorkflowSync
from teleclaude.core.workflow_store.selection import selected_workflow_store_config
from teleclaude.core.workflow_store.types import StoreCapabilities
from teleclaude.types.github_binding import GitHubActorAssignment

if TYPE_CHECKING:
    from .store import WorkflowStore

_MISSING_APP = "GitHub workflow store requires todos.app to name a configured platform App"
_UNKNOWN_APP = "GitHub workflow store todos.app does not match a configured platform App"
_MIGRATION_RECORD_ID = "github-store-switch:{}:{}"
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
