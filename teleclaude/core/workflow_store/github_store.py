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
from teleclaude.core.todos_db._github_artifacts import (
    ArtifactFact,
    EntryRow,
    artifact_address,
    committed_entries,
    issue_artifacts_fact,
    keep_hydrated_version,
    local_republication_pending,
    read_republication_wait,
    republication_pending,
    save_issue_artifacts_fact,
)
from teleclaude.core.todos_db._github_board import board_setup, mark_all_board_items_owed_at, owed_board_items
from teleclaude.core.todos_db._github_pull_requests import work_item_for_number
from teleclaude.core.todos_db._github_questions import insert_awaiting_question
from teleclaude.core.todos_db._rows import ArtifactVersionRow, ArtifactWritersRow
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
from teleclaude.core.workflow_store.github_artifact_values import served_version_content
from teleclaude.core.workflow_store.github_board_io import GitHubBoardIO
from teleclaude.core.workflow_store.github_board_queue import repair_owed_board_items
from teleclaude.core.workflow_store.github_board_setup import BoardRepairOutcome, BoardSetupCause, GitHubBoardSetup
from teleclaude.core.workflow_store.github_io import GitHubMutationPacing, GitHubWorkflowIO
from teleclaude.core.workflow_store.github_io_models import GitHubArtifactType
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused
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
from teleclaude.utils.transcript_discovery import as_session_id

if TYPE_CHECKING:
    from .store import WorkflowStore

_MISSING_APP = "GitHub workflow store requires todos.app to name a configured platform App"
_UNKNOWN_APP = "GitHub workflow store todos.app does not match a configured platform App"
_EMPTY = ""
_QUESTION_LINE_BREAK = "\n"
_MIGRATION_RECORD_ID = "github-store-switch:{}:{}"
_ITEM_ID_BY_SLUG = "SELECT CAST(id AS TEXT) FROM todo WHERE slug = :slug"
_REMOVED_ITEM_IDS_BY_SLUG = f"SELECT CAST(id AS TEXT) FROM todo WHERE slug = :slug AND status = '{TodoStatus.REMOVED}'"
_LIVE_ITEM_ID_BY_SLUG = (
    f"SELECT CAST(id AS TEXT) FROM todo WHERE slug = :slug AND status IN ('{TodoStatus.ACTIVE}', '{TodoStatus.ICEBOX}')"
)
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
_BOARD_SETUP_FAILED = "github_store_board_setup_failed"
_ITEM_ID = "item_id"
_PROBE_PAGE_SIZE = 1
_LEDGER_ISSUE_NUMBER = "SELECT ledger_issue_number FROM github_repository WHERE singleton = 1"
_ANY_ITEM_ISSUE_NUMBER = "SELECT issue_number FROM github_item WHERE issue_number IS NOT NULL LIMIT 1"
logger = get_logger(__name__)
_unreadable_working_copies: set[Path] = set()
_instances: dict[str, GitHubWorkflowStore] = {}
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()
_new_instance_hook: Callable[[WorkflowStore, str], None] | None = None


class GitHubStoreSelectionRefused(ValueError):
    """The project's ``todos.app`` is missing or names no configured platform App, so no store is selected."""


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
        self._board = GitHubBoardIO(repository, assignment)
        self._push = GitHubWorkflowPush(path, repository, assignment, self._io, self._pull_requests, self._board)
        self._board_setup_lock = asyncio.Lock()
        self._sync = GitHubWorkflowSync(self, repository, assignment, self._io, self._pull_requests, self._board)
        self._push.set_conflict_refresh(self._sync.refresh)
        self.set_commit_callbacks(
            self._push.before_commit,
            self._push.after_commit,
            after_transaction_end=self._push.refresh_after_conflict,
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
        self.serve_async_callers()

    def serve_async_callers(self) -> None:
        """Make the running loop the one where conflict recovery is scheduled for this store."""
        self._push.serve_conflict_refresh_on(asyncio.get_running_loop())

    async def close(self) -> None:
        """Stop an in-flight conflict refresh before the storage it uses is disposed."""
        await self._push.stop_conflict_refresh()
        await super().close()

    def initialize_github_sync(self) -> None:
        """Synchronous sibling for CLI and integration processes."""
        self.initialize_sync()
        initialize_working_copy(self.db_path)

    async def rebuild(self) -> None:
        """Populate a newly created working copy from the repository before serving it."""
        await self._sync.rebuild()

    async def admit_item_write(
        self, *, slug: str | None = None, todo_id: str | None = None, retained: bool = False
    ) -> None:
        """Refuse the write of an item that awaits republication, and mark it requested.

        The mark moves the item to the front of republication on the computer that holds its content, written from
        a thread no request depends on, as a refused push does.
        """
        async with self._session() as session:
            item_id = await session.run_sync(_pending_item, slug, todo_id, retained)
        if item_id is None:
            return
        self._push.request_republication(item_id)
        raise GitHubIORefused(GitHubIOFailure.AWAITING_REPUBLICATION)

    async def refresh_working_copy(self, *, republish: bool = False) -> int:
        """Adopt committed changes made by another computer and repair owed reflections.

        `republish` lets the repair publish the items whose record predates native artifacts.
        """
        return await self._sync.refresh(republish=republish)

    async def ensure_issue_artifacts(self) -> None:
        """Establish that the repository serves issue artifacts, refusing with the distinct cause when it does not.

        While the recorded fact is unknown or not-served, one list on a platform issue, filtered to a type the platform
        never creates, answers it and so carries no workflow body. A served repository
        needs no request. With no platform issue to ask, the first artifact request establishes the fact.
        """
        async with self._session() as session:
            fact, target = await session.run_sync(_probe_target)
        if fact is ArtifactFact.SERVED or target is None:
            return
        try:
            await self._io.async_list_artifacts(target, GitHubArtifactType.LINK, _PROBE_PAGE_SIZE)
        except GitHubIORefused as refused:
            if refused.reason is GitHubIOFailure.ISSUE_ARTIFACTS_UNAVAILABLE:
                await self._record_fact(ArtifactFact.NOT_SERVED)
            raise
        await self._record_fact(ArtifactFact.SERVED)

    async def _record_fact(self, fact: ArtifactFact) -> None:
        async with self._session() as session:
            async with session.begin():
                await session.run_sync(acquire_repository_writer)
                await session.run_sync(save_issue_artifacts_fact, fact)

    def ensure_issue_artifacts_sync(self) -> None:
        """Synchronous sibling of `ensure_issue_artifacts` for CLI and integration processes."""
        with self._sync_session() as session:
            fact, target = _probe_target(session)
        if fact is ArtifactFact.SERVED or target is None:
            return
        try:
            self._io.list_artifacts(target, GitHubArtifactType.LINK, _PROBE_PAGE_SIZE)
        except GitHubIORefused as refused:
            if refused.reason is GitHubIOFailure.ISSUE_ARTIFACTS_UNAVAILABLE:
                self._record_fact_sync(ArtifactFact.NOT_SERVED)
            raise
        self._record_fact_sync(ArtifactFact.SERVED)

    def _record_fact_sync(self, fact: ArtifactFact) -> None:
        with self._sync_session() as session:
            with session.begin():
                acquire_repository_writer(session)
                save_issue_artifacts_fact(session, fact)

    async def artifact_versions(self, slug: str, name: str, *, limit: int = 50) -> list[ArtifactVersionRow]:
        """Version history of an artifact; versions a rebuilt copy lacks are read from GitHub once, on first use."""
        await self._hydrate_versions(slug, name, limit=limit)
        return await super().artifact_versions(slug, name, limit=limit)

    async def artifacts_diff(
        self, slug: str, name: str, old_digest: str, new_digest: str, *, include_removed: bool = False
    ) -> str:
        await self._hydrate_versions(
            slug, name, digests=frozenset({old_digest, new_digest}), include_removed=include_removed
        )
        return await super().artifacts_diff(slug, name, old_digest, new_digest, include_removed=include_removed)

    async def list_artifacts_with_writers(
        self, slug: str, *, include_removed: bool = False
    ) -> list[ArtifactWritersRow]:
        """Writers across each artifact's versions: the committed record's, then any only the copy holds."""
        rows = await super().list_artifacts_with_writers(slug, include_removed=include_removed)
        async with self._session() as session:
            item_id = await self._resolve_artifact_id(slug, session, include_removed=include_removed)
            entries = await session.run_sync(committed_entries, item_id) if item_id is not None else ()
        named: dict[str, list[str]] = {}
        for entry in entries:
            writer = as_session_id(entry.updated_by)
            if writer and writer not in named.setdefault(entry.name, []):
                named[entry.name].append(writer)
        return [
            ArtifactWritersRow(
                name=row["name"],
                writers=[
                    *named.get(row["name"], []),
                    *(w for w in row["writers"] if w not in named.get(row["name"], [])),
                ],
            )
            for row in rows
        ]

    async def _hydrate_versions(
        self,
        slug: str,
        name: str,
        *,
        limit: int | None = None,
        digests: frozenset[str] | None = None,
        include_removed: bool = False,
    ) -> None:
        """Keep the requested versions a committed record names but this copy holds no content for.

        One single-artifact read serves them all; a refused read refuses the caller with the provider's cause and
        keeps nothing. A version GitHub no longer serves stays absent, as for any version the copy never had.
        """
        async with self._session() as session:
            item_id = await self._resolve_artifact_id(slug, session, include_removed=include_removed)
            if item_id is None:
                return
            entries, issue_number, artifact_number = await session.run_sync(_hydration_target, item_id, name)
        newest_first = sorted((entry for entry in entries if entry.name == name), key=lambda e: -e.ordinal)
        wanted = [
            entry
            for entry in (newest_first[:limit] if limit is not None else newest_first)
            if entry.version_id is None and (digests is None or entry.digest in digests)
        ]
        if not wanted or issue_number is None or artifact_number is None:
            return
        history = await self._io.async_read_artifact(issue_number, artifact_number)
        found = [
            (entry, content)
            for entry in wanted
            if (content := served_version_content(history.versions, self._assignment.actor.id, entry.digest))
            is not None
        ]
        if not found:
            return
        async with self._session() as session:
            async with session.begin():
                await session.run_sync(acquire_repository_writer)
                for entry, content in found:
                    await session.run_sync(keep_hydrated_version, item_id, entry, content)

    async def refresh_board_setup(self, computer: str) -> None:
        """Set the project's board up when none is recorded or setup is owed; only the daemon calls this."""
        async with self._board_setup_lock:
            async with self._session() as session:
                setup, owed = await session.run_sync(
                    lambda sync_session: (board_setup(sync_session), owed_board_items(sync_session))
                )
            if setup.owed_cause == BoardSetupCause.PERSONAL_ACCOUNT or not (
                setup.targets() is None or setup.owed_cause is not None or owed
            ):
                return
            await self._board_setup(computer).run()

    async def repair_board(self, computer: str) -> BoardRepairOutcome:
        """Owe every item's board item, set the board up and write them all; only the daemon calls this."""
        async with self._board_setup_lock:
            await asyncio.to_thread(mark_all_board_items_owed_at, Path(self.db_path))
            setup = await self._board_setup(computer).run()
            left = await repair_owed_board_items(self, self._board, set())
            async with self._session() as session:
                slugs = await session.run_sync(
                    lambda sync_session: [_slug_of(sync_session, item_id) for item_id, _reason in left]
                )
            return BoardRepairOutcome(
                setup=setup,
                unwritten=tuple((slug, reason) for slug, (_item_id, reason) in zip(slugs, left, strict=True)),
            )

    def _board_setup(self, computer: str) -> GitHubBoardSetup:
        return GitHubBoardSetup(Path(self.db_path), self._repository, self._assignment, self._io, self._board, computer)

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
    root, identity, assignment = resolve_github_store_selection(project_root_or_cwd)
    key = str(github_working_copy_path(root))
    lock = _lock_for(key)
    await asyncio.to_thread(lock.acquire)
    try:
        existing = _instances.get(key)
        if existing is not None:
            existing.serve_async_callers()
            await existing.ensure_issue_artifacts()
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
        await store.ensure_issue_artifacts()
        return store
    finally:
        lock.release()


def get_github_workflow_store_sync(project_root_or_cwd: str | Path) -> WorkflowStore:
    """Synchronous resolver sharing the canonical-root cache with async callers."""
    root, identity, assignment = resolve_github_store_selection(project_root_or_cwd)
    key = str(github_working_copy_path(root))
    lock = _lock_for(key)
    lock.acquire()
    try:
        existing = _instances.get(key)
        if existing is not None:
            existing.ensure_issue_artifacts_sync()
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
        store.ensure_issue_artifacts_sync()
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


async def refresh_github_workflow_store(
    project_root_or_cwd: str | Path, *, computer: str, republish: bool = False
) -> int:
    """Refresh the selected project's shared GitHub working copy from the daemon.

    The daemon alone sets the project's board up, as `computer`, ahead of the refresh so the items the
    setup owes are written by it. While a throttle met by republication holds the project, nothing is
    requested at all, not even to resolve the store. `republish` lets this refresh also publish the items whose
    record predates native artifacts; only the computer that works the project passes it.
    """
    if republication_held(project_root_or_cwd):
        return 0
    store = cast(GitHubWorkflowStore, await get_github_workflow_store(project_root_or_cwd))
    try:
        await store.refresh_board_setup(computer)
    except Exception as error:  # supervision boundary: the board never holds back the refresh
        logger.warning(_BOARD_SETUP_FAILED, reason=type(error).__name__, exc_info=True)
    return await store.refresh_working_copy(republish=republish)


def republication_held(project_root_or_cwd: str | Path) -> bool:
    """Whether a throttle met by republication still holds the project's automatic refresh.

    Reads only the existing working copy, with no writer, rebuild or provider call.
    """
    path = github_working_copy_path(resolve_github_store_selection(project_root_or_cwd)[0])
    if not path.is_file():
        return False
    try:
        with _open_working_copy_read_only(path) as session:
            not_before = read_republication_wait(session).not_before
    except DBAPIError:
        return False
    return not_before is not None and not_before > datetime.now(UTC)


def republication_owed(project_root_or_cwd: str | Path) -> bool:
    """Whether the project's working copy holds items it can republish: their record predates native artifacts."""
    path = github_working_copy_path(resolve_github_store_selection(project_root_or_cwd)[0])
    if not path.is_file():
        return False
    try:
        with _open_working_copy_read_only(path) as session:
            return local_republication_pending(session)
    except DBAPIError:
        return False


async def repair_github_board(project_root_or_cwd: str | Path, *, computer: str) -> BoardRepairOutcome:
    """Rebuild every item, lane and marker on the selected project's board from its GitHub store."""
    store = cast(GitHubWorkflowStore, await get_github_workflow_store(project_root_or_cwd))
    return await store.repair_board(computer)


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


def resolve_github_store_selection(
    project_root_or_cwd: str | Path,
) -> tuple[Path, GitHubRepositoryIdentity, GitHubActorAssignment]:
    identity = resolve_github_repository_identity(project_root_or_cwd)
    selection: TodoStoreConfig = selected_workflow_store_config(identity.project_path)
    if selection.app is None:
        raise GitHubStoreSelectionRefused(_MISSING_APP)
    assignment = github_actor_for_app_id(selection.app)
    if assignment is None:
        raise GitHubStoreSelectionRefused(_UNKNOWN_APP)
    return identity.project_path, identity, assignment


def _pending_item(session: SyncSession, slug: str | None, todo_id: str | None, retained: bool) -> str | None:
    """The addressed item's id when it is in the pending set, resolving its identity once.

    A slug addresses its live (active or icebox) item, as a state read does: a slug no live item bears is a
    creation key or an unknown name. A request that addresses a removed item (`retained`) addresses the slug's
    removed item, the one its reactivation acts on, and none when more than one is removed. An id addresses its
    item exactly.
    """
    if todo_id is None and slug is not None:
        if retained:
            removed = session.execute(text(_REMOVED_ITEM_IDS_BY_SLUG), {_SLUG: slug}).scalars().all()
            todo_id = str(removed[0]) if len(removed) == 1 else None
        else:
            found = session.execute(text(_LIVE_ITEM_ID_BY_SLUG), {_SLUG: slug}).scalar_one_or_none()
            todo_id = str(found) if found is not None else None
    return todo_id if todo_id is not None and republication_pending(session, todo_id) else None


def _probe_target(session: SyncSession) -> tuple[ArtifactFact | None, int | None]:
    """The recorded artifact fact and the platform issue to ask about it: the ledger's, else any item's."""
    fact = issue_artifacts_fact(session)
    if fact is ArtifactFact.SERVED:
        return fact, None
    number = session.execute(text(_LEDGER_ISSUE_NUMBER)).scalar_one_or_none()
    if not isinstance(number, int):
        number = session.execute(text(_ANY_ITEM_ISSUE_NUMBER)).scalar_one_or_none()
    return fact, number if isinstance(number, int) else None


def _hydration_target(
    session: SyncSession, item_id: str, name: str
) -> tuple[tuple[EntryRow, ...], int | None, int | None]:
    bookkeeping = item_bookkeeping(session, item_id)
    issue_number = bookkeeping.get(WorkflowField.ISSUE_NUMBER) if bookkeeping is not None else None
    return (
        committed_entries(session, item_id),
        issue_number if isinstance(issue_number, int) else None,
        artifact_address(session, item_id, name),
    )


def _slug_of(session: SyncSession, item_id: str) -> str:
    slug = session.execute(text(_ITEM_SLUG_BY_ID), {_ITEM_ID: item_id}).scalar_one_or_none()
    return slug if isinstance(slug, str) else item_id


def _lock_for(key: str) -> threading.Lock:
    with _guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock
