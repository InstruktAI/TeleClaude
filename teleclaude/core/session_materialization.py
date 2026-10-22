"""Serialize local session source reads, projection, and cache publication."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core.session_snapshot import (
    SessionIssueAssignment,
    SessionIssueMetadata,
    project_session_snapshot_from_source,
    resolve_session_issue_assignment,
    resolve_session_issue_metadata,
)
from teleclaude.core.session_status import is_session_final

if TYPE_CHECKING:
    from teleclaude.core.cache import DaemonCache
    from teleclaude.core.db import Db
    from teleclaude.core.models._session import Session
    from teleclaude.core.models._snapshot import SessionSnapshot
    from teleclaude.core.task_registry import SupervisedTask, TaskRegistry

logger = get_logger(__name__)

_MATERIALIZER_WORKER_COUNT = 2
_RESOLVED_METADATA_LIMIT = 256
_MATERIALIZER_WORKER_NAME = "session-enrichment-materializer"
_ENRICHMENT_FAILED_EVENT = "session_enrichment_failed"
_SOURCE_RETRY_TASK = "session-source-reconciliation"
_SOURCE_RETRY_FAILED_EVENT = "session_source_retry_failed"
_SOURCE_RETRY_PAUSE_S = 1.0


@dataclass
class _SessionLockEntry:
    lock: asyncio.Lock
    users: int = 0


class SessionMaterializer:
    """Own serialized local session reconciliation and optional enrichment."""

    def __init__(self, runtime_db: Db, cache: DaemonCache, *, computer: str) -> None:
        self._db = runtime_db
        self._cache = cache
        self._computer = computer
        self._locks: dict[str, _SessionLockEntry] = {}
        self._locks_guard = asyncio.Lock()
        self._enrichment_queue: asyncio.Queue[SessionIssueAssignment] = asyncio.Queue()
        self._enrichment_queued: set[SessionIssueAssignment] = set()
        self._resolved_metadata: OrderedDict[SessionIssueAssignment, SessionIssueMetadata] = OrderedDict()
        self._enrichment_workers: list[asyncio.Task[None]] = []
        self._source_retry: SupervisedTask | None = None
        self._dirty_sources: set[str] = set()
        self._source_versions: dict[str, int] = {}
        self._source_generation = 0
        self._source_changed = asyncio.Event()
        self._stopping = False

    def start(self, task_registry: TaskRegistry) -> None:
        """Start the bounded enrichment workers owned by the daemon lifecycle."""
        if self._enrichment_workers:
            return
        self._stopping = False
        self._source_retry = task_registry.supervise(_SOURCE_RETRY_TASK, self._retry_sources, restart=True)
        self._enrichment_workers = [
            task_registry.spawn(self._enrichment_worker(), name=_MATERIALIZER_WORKER_NAME)
            for _ in range(_MATERIALIZER_WORKER_COUNT)
        ]

    async def stop(self) -> None:
        """Stop enrichment workers before their database dependency closes."""
        self._stopping = True
        if self._source_retry is not None:
            await self._source_retry.cancel()
            self._source_retry = None
        workers = tuple(self._enrichment_workers)
        self._enrichment_workers.clear()
        for worker in workers:
            worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)

    async def reconcile(self, session_id: str) -> SessionSnapshot | None:
        """Re-read one session's current owner state and publish it to the cache."""
        self._source_generation += 1
        version = self._source_generation
        self._source_versions[session_id] = version
        try:
            snapshot = await self._reconcile_source(session_id)
        except (Exception, asyncio.CancelledError):
            self._dirty_sources.add(session_id)
            self._source_changed.set()
            raise
        if self._source_versions.get(session_id) == version:
            self._dirty_sources.discard(session_id)
            self._source_versions.pop(session_id, None)
        return snapshot

    async def _retry_sources(self) -> None:
        """Retry dirty identities without retaining obsolete event payloads."""
        while not self._stopping:
            await self._source_changed.wait()
            self._source_changed.clear()
            for session_id in tuple(self._dirty_sources):
                try:
                    await self.reconcile(session_id)
                except Exception:
                    logger.exception(_SOURCE_RETRY_FAILED_EVENT, session_id=session_id)
            if self._dirty_sources:
                await asyncio.sleep(_SOURCE_RETRY_PAUSE_S)

    async def reconcile_current(self) -> None:
        """Repair open sources and cached local rows at a live delivery handover."""
        sources = await self.source_sessions()
        identities = {source.session_id for source in sources}
        identities.update(row.session_id for row in self._cache.get_sessions() if row.computer == self._computer)
        await self.reconcile_many(sorted(identities))

    async def source_sessions(self) -> list[Session]:
        """Read the current local source set used by projection recovery."""
        return await self._db.list_sessions(computer_name=self._computer, all_open=True)

    async def _reconcile_source(self, session_id: str) -> SessionSnapshot | None:
        assignment: SessionIssueAssignment | None = None
        async with self._session_lock(session_id):
            source = await self._db.get_session(session_id)
            if source is None:
                self._remove_local_row(session_id)
                return None
            assignment = await resolve_session_issue_assignment(self._db, source)
            current = await self._db.get_session(session_id)
            if current is None or self._source_is_final(current):
                self._remove_local_row(session_id)
                return None
            metadata = self._resolved_metadata.get(assignment) if assignment is not None else None
            if metadata is not None and assignment is not None:
                self._resolved_metadata.move_to_end(assignment)
            if metadata is not None and not metadata.applies_to(current):
                metadata = None
            snapshot = project_session_snapshot_from_source(
                current,
                computer=self._computer,
                issue_metadata=metadata,
            )
            self._publish_snapshot(snapshot)
        if assignment is not None and assignment not in self._resolved_metadata:
            await self._queue_enrichment(assignment)
        return snapshot

    async def reconcile_many(self, session_ids: list[str]) -> None:
        """Reconcile session identities serially, reading each row at its own turn."""
        for session_id in session_ids:
            await self.reconcile(session_id)

    async def _queue_enrichment(self, assignment: SessionIssueAssignment) -> None:
        if self._stopping or assignment in self._resolved_metadata or assignment in self._enrichment_queued:
            return
        self._enrichment_queued.add(assignment)
        self._enrichment_queue.put_nowait(assignment)

    async def _enrichment_worker(self) -> None:
        while not self._stopping:
            assignment = await self._enrichment_queue.get()
            try:
                metadata = await resolve_session_issue_metadata(assignment)
                if metadata.reference is not None:
                    next_assignment: SessionIssueAssignment | None = None
                    async with self._session_lock(assignment.session_id):
                        current = await self._db.get_session(assignment.session_id)
                        if current is not None and not self._source_is_final(current):
                            current_assignment = await resolve_session_issue_assignment(self._db, current)
                            fresh = await self._db.get_session(assignment.session_id)
                            if (
                                fresh is not None
                                and not self._source_is_final(fresh)
                                and current_assignment == assignment
                                and metadata.applies_to(fresh)
                            ):
                                self._resolved_metadata[assignment] = metadata
                                self._resolved_metadata.move_to_end(assignment)
                                while len(self._resolved_metadata) > _RESOLVED_METADATA_LIMIT:
                                    self._resolved_metadata.popitem(last=False)
                                snapshot = project_session_snapshot_from_source(
                                    fresh,
                                    computer=self._computer,
                                    issue_metadata=metadata,
                                )
                                self._publish_snapshot(snapshot)
                            elif current_assignment is not None:
                                next_assignment = current_assignment
                    if next_assignment is not None:
                        await self._queue_enrichment(next_assignment)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning(
                    _ENRICHMENT_FAILED_EVENT,
                    session_id=assignment.session_id,
                    error=str(error),
                    exc_info=True,
                )
            finally:
                self._enrichment_queued.discard(assignment)
                self._enrichment_queue.task_done()

    def _publish_snapshot(self, snapshot: SessionSnapshot) -> None:
        if self._cache.get_session(snapshot.session_id) != snapshot:
            self._cache.update_session(snapshot)

    def _remove_local_row(self, session_id: str) -> None:
        cached = self._cache.get_session(session_id)
        if cached is not None and cached.computer == self._computer:
            self._cache.remove_session(session_id)

    @staticmethod
    def _source_is_final(session: Session) -> bool:
        return bool(session.deleted_at) or is_session_final(
            lifecycle_status=session.lifecycle_status, closed_at=session.closed_at
        )

    @asynccontextmanager
    async def _session_lock(self, session_id: str) -> AsyncIterator[None]:
        async with self._locks_guard:
            entry = self._locks.get(session_id)
            if entry is None:
                entry = _SessionLockEntry(asyncio.Lock())
                self._locks[session_id] = entry
            entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            async with self._locks_guard:
                entry.users -= 1
                if entry.users == 0 and not entry.lock.locked():
                    self._locks.pop(session_id, None)
