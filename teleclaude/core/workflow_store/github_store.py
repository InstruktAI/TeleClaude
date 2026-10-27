"""GitHub-backed workflow store that reuses the local implementation on a disposable copy."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger
from pydantic import HttpUrl
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session as SyncSession

from teleclaude.config.identity_schema import PersonEntry
from teleclaude.config.loader import github_actor_for_app_id
from teleclaude.config.project_models import TodoStoreBackend, TodoStoreConfig
from teleclaude.constants import TodoStatus
from teleclaude.core.todos_db._adapter import TodosDb
from teleclaude.core.todos_db._github_pull_requests import work_item_for_number
from teleclaude.core.todos_db._github_questions import insert_awaiting_question
from teleclaude.core.todos_db._working_copy import (
    WorkingCopyField,
    WorkingCopyItemSnapshot,
    acquire_repository_writer,
    item_bookkeeping,
    item_snapshot,
    mark_reflection_owed,
    repository_initialized,
    restore_item_snapshot,
    restore_project_record,
)
from teleclaude.core.todos_db._working_copy_schema import initialize_working_copy
from teleclaude.core.todos_db._write_admission import WRITE_ADMISSION_BUDGET_S
from teleclaude.core.todos_db_path import github_working_copy_path
from teleclaude.core.workflow_store.github import (
    GitHubIdentityRefused,
    GitHubRepositoryIdentity,
    resolve_github_repository_identity,
)
from teleclaude.core.workflow_store.github_io import GitHubMutationPacing, GitHubWorkflowIO
from teleclaude.core.workflow_store.github_pull_request_io import GitHubPullRequestIO
from teleclaude.core.workflow_store.github_push import GitHubWorkflowPush
from teleclaude.core.workflow_store.github_push_deadline import await_within_push_deadline, begin_push_deadline
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
from teleclaude.project_manifest import load_roots
from teleclaude.project_root import is_project_checkout
from teleclaude.types.github_binding import GitHubActorAssignment
from teleclaude.types.github_issue import GitHubIssueReference

if TYPE_CHECKING:
    from .store import WorkflowStore

_MISSING_APP = "GitHub workflow store requires todos.app to name a configured platform App"
_UNKNOWN_APP = "GitHub workflow store todos.app does not match a configured platform App"
_EMPTY = ""
_QUESTION_LINE_BREAK = "\n"
_MIGRATION_RECORD_ID = "github-store-switch:{}:{}"
_ITEM_ID_BY_SLUG = "SELECT CAST(id AS TEXT) FROM todo WHERE slug = :slug"
_ITEM_SLUG_BY_ID = "SELECT slug FROM todo WHERE CAST(id AS TEXT) = :item_id"
_ITEM_STATE_BY_ID = "SELECT state FROM todo_state WHERE CAST(id AS TEXT) = :item_id"
_LIVE_ITEM_ISSUE_NUMBER = (
    "SELECT i.issue_number FROM todo AS t JOIN github_item AS i ON CAST(t.id AS TEXT) = i.item_id "
    f"WHERE t.slug = :slug AND t.status IN ('{TodoStatus.ACTIVE}', '{TodoStatus.ICEBOX}')"
)
_SLUG = "slug"
_ISSUE_URL = "https://github.com/{}/issues/{}"
_ISSUE_UNREADABLE_EVENT = "github_item_issue_unreadable"
_READ_ONLY_URI = "file:{}?mode=ro"
_IN_MEMORY_ENGINE_URL = "sqlite://"
_ACTIVE_RUNNER = "active_runner"
_ITEM_ID = "item_id"
logger = get_logger(__name__)
_unreadable_working_copies: set[Path] = set()
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
        super().__init__(str(path), write_admission_budget=WRITE_ADMISSION_BUDGET_S)
        self._repository = repository
        self._assignment = assignment
        self._migration_lock = asyncio.Lock()
        self._io = GitHubWorkflowIO(repository, assignment)
        self._pull_requests = GitHubPullRequestIO(repository)
        self._push = GitHubWorkflowPush(path, repository, assignment, self._io, self._pull_requests)
        self._sync = GitHubWorkflowSync(self, repository, assignment, self._io, self._pull_requests)
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
                await await_within_push_deadline(
                    begin_push_deadline(),
                    self._io.async_create_comment(issue_number_value, body),
                    commit_point_sent=False,
                )
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


@dataclass(frozen=True)
class GitHubWorkItem:
    """A work item found by its issue or pull request number, with the session holding its claim."""

    project_root: Path
    slug: str
    active_runner: str | None


def find_github_work_item(repository_id: int, number: int) -> GitHubWorkItem | None:
    """Find the item an issue or pull request number of a repository belongs to on this computer.

    Reads only a working copy that already exists: no provider call, no rebuild.
    """
    for project_root in load_roots():
        if not project_root.exists() or not is_project_checkout(project_root):
            continue
        try:
            identity = resolve_github_repository_identity(project_root)
        except GitHubIdentityRefused:
            continue
        if identity.repository_id != repository_id:
            continue
        found = _read_work_item(identity.project_path, number)
        if found is not None:
            return found
    return None


@contextmanager
def _open_working_copy_read_only(path: Path) -> Iterator[SyncSession]:
    """Open an existing working copy without the writer lock, a rebuild or a provider call."""
    engine = create_engine(
        _IN_MEMORY_ENGINE_URL, creator=lambda: sqlite3.connect(_READ_ONLY_URI.format(path), uri=True)
    )
    try:
        with SyncSession(engine) as session:
            yield session
    finally:
        engine.dispose()


def _read_work_item(project_root: Path, number: int) -> GitHubWorkItem | None:
    path = github_working_copy_path(project_root)
    if not path.is_file():
        return None
    with _open_working_copy_read_only(path) as session:
        item_id = work_item_for_number(session, number)
        if item_id is None:
            return None
        slug = session.execute(text(_ITEM_SLUG_BY_ID), {_ITEM_ID: item_id}).scalar_one_or_none()
        state_value = session.execute(text(_ITEM_STATE_BY_ID), {_ITEM_ID: item_id}).scalar_one_or_none()
    if not isinstance(slug, str):
        return None
    try:
        state = json.loads(state_value) if isinstance(state_value, str) else {}
    except json.JSONDecodeError:
        state = {}
    runner = state.get(_ACTIVE_RUNNER) if isinstance(state, dict) else None
    return GitHubWorkItem(project_root, slug, runner if isinstance(runner, str) and runner else None)


def read_github_item_issue(project_root: str | Path, slug: str) -> GitHubIssueReference | None:
    """Read the issue the store recorded for the live item with this slug.

    Answers only from a working copy that already exists: no provider call, no rebuild, no writer lock.
    Returns None for a project outside the GitHub store, a missing working copy, an item that is not
    live, or an item the store has not yet given an issue.
    """
    try:
        identity = resolve_github_repository_identity(project_root)
    except GitHubIdentityRefused:
        return None
    path = github_working_copy_path(identity.project_path)
    if not path.is_file():
        return None
    try:
        with _open_working_copy_read_only(path) as session:
            number = session.execute(text(_LIVE_ITEM_ISSUE_NUMBER), {_SLUG: slug}).scalar_one_or_none()
    except DBAPIError as error:
        # Issue navigation is optional: an unreadable working copy must not make a session projection fail.
        if identity.project_path not in _unreadable_working_copies:
            _unreadable_working_copies.add(identity.project_path)
            cause = error.orig if error.orig is not None else error
            logger.warning(
                _ISSUE_UNREADABLE_EVENT,
                project_path=str(identity.project_path),
                error_type=type(cause).__name__,
                reason=str(cause),
            )
        return None
    _unreadable_working_copies.discard(identity.project_path)
    if not isinstance(number, int):
        return None
    return GitHubIssueReference(number=number, url=HttpUrl(_ISSUE_URL.format(identity.repository, number)))


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
