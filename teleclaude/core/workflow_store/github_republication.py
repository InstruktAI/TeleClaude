"""Republish the items whose record predates native artifacts, one paced item at a time.

Saves go outside the working copy's writer and are recorded as save progress; the item's committed record is
then written by a finalizing push, the one write the awaiting-republication refusal admits.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta

from instrukt_ai_logging import get_logger
from sqlalchemy.orm import Session

from teleclaude.core.todos_db._adapter import TodosDb
from teleclaude.core.todos_db._github_artifacts import (
    REPUBLICATION_FINALIZING_KEY,
    ProgressRow,
    RepublicationWait,
    clear_republication_item,
    mark_pending_item,
    read_republication_wait,
    republication_order,
    republication_pending,
    republication_progress,
    save_republication_progress,
    save_republication_wait,
)
from teleclaude.core.todos_db._working_copy import (
    WorkingCopyItemSnapshot,
    acquire_repository_writer,
    item_bookkeeping,
    item_snapshot,
)
from teleclaude.core.workflow_store.github import GitHubRepositoryIdentity
from teleclaude.core.workflow_store.github_artifact_values import artifact_type
from teleclaude.core.workflow_store.github_io import GitHubWorkflowIO
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused
from teleclaude.core.workflow_store.github_record import WorkflowField
from teleclaude.core.workflow_store.github_reflection import is_repository_work
from teleclaude.types.github_binding import GitHubActorAssignment

__all__ = ["GitHubRepublication"]

_FIRST_PAUSE = timedelta(minutes=1)
_LONGEST_PAUSE = timedelta(hours=1)
logger = get_logger(__name__)


class GitHubRepublication:
    """Publish pending items' versions as native issue-artifact versions and commit their schema-2 records."""

    def __init__(
        self,
        store: TodosDb,
        repository: GitHubRepositoryIdentity,
        assignment: GitHubActorAssignment,
        io: GitHubWorkflowIO,
    ) -> None:
        self.store = store
        self.repository = repository
        self.assignment = assignment
        self.io = io

    async def run(self) -> None:
        """Republish the pending set in priority order.

        A throttle records the wait it implies and propagates, ending the enclosing refresh; any other
        refusal ends the pass and the next refresh retries.
        """
        async with self.store._session() as session:
            order = await session.run_sync(republication_order)
        if not order:
            return
        async with self.io.paced_mutations(lifts_push_deadline=False) as pacing:
            for item_id in order:
                try:
                    await self._republish(item_id)
                except GitHubIORefused as refused:
                    if refused.reason is GitHubIOFailure.RATE_LIMITED:
                        await self._record_throttle(refused)
                        raise
                    logger.warning("github_store_republication_refused", item_id=item_id, reason=refused.reason.value)
                    return
                await pacing.wait_between_items()

    async def _republish(self, item_id: str) -> None:
        async with self.store._session() as session:
            snapshot, issue_number, progress = await session.run_sync(_read_item, item_id)
        if snapshot is None or issue_number is None or not is_repository_work(snapshot.state):
            await self._transaction(clear_republication_item, item_id)
            return
        saved = {row.version_id for row in progress}
        numbers = {row.name: row.artifact_number for row in progress}
        for version in snapshot.versions:
            version_id = version.get(WorkflowField.VERSION_ID)
            name = version.get(WorkflowField.NAME)
            digest = version.get(WorkflowField.DIGEST)
            content = version.get(WorkflowField.CONTENT)
            if (
                not isinstance(version_id, int)
                or not isinstance(name, str)
                or not isinstance(digest, str)
                or not isinstance(content, str)
            ):
                raise GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED)
            if version_id in saved:
                continue
            number = numbers.get(name)
            if number is None:
                artifact = await self.io.async_create_artifact(issue_number, artifact_type(name), name, content)
            else:
                artifact = await self.io.async_update_artifact(issue_number, number, content)
            numbers[name] = artifact.number
            if not await self._transaction(_record_save, item_id, name, version_id, digest, artifact.number):
                return
        await self._finalize(item_id)
        logger.debug("github_store_item_republished", item_id=item_id, issue_number=issue_number)

    async def _finalize(self, item_id: str) -> None:
        """Commit the item's record through the ordinary push, marked as the item's republication."""
        async with self.store._session() as session:
            session.sync_session.info[REPUBLICATION_FINALIZING_KEY] = item_id
            try:
                async with session.begin():
                    await session.run_sync(acquire_repository_writer)
                    await session.run_sync(mark_pending_item, item_id)
            finally:
                session.sync_session.info.pop(REPUBLICATION_FINALIZING_KEY, None)

    async def _record_throttle(self, refused: GitHubIORefused) -> None:
        """Hold the automatic refresh until the resume time GitHub named, or a pause that doubles per throttle."""
        async with self.store._session() as session:
            held = await session.run_sync(read_republication_wait)
        now = datetime.now(UTC)
        if refused.resume_at is not None:
            wait = RepublicationWait(refused.resume_at, held.backoff_seconds)
        else:
            pause = min(max(timedelta(seconds=held.backoff_seconds * 2), _FIRST_PAUSE), _LONGEST_PAUSE)
            wait = RepublicationWait(now + pause, int(pause.total_seconds()))
        await self._transaction(save_republication_wait, wait)
        logger.warning(
            "github_store_republication_throttled", not_before=wait.not_before.isoformat() if wait.not_before else None
        )

    async def _transaction[Result](self, operation: Callable[..., Result], *arguments: object) -> Result:
        async with self.store._session() as session:
            async with session.begin():
                await session.run_sync(acquire_repository_writer)
                return await session.run_sync(operation, *arguments)


def _read_item(
    session: Session, item_id: str
) -> tuple[WorkingCopyItemSnapshot | None, int | None, tuple[ProgressRow, ...]]:
    snapshot = item_snapshot(session, item_id)
    bookkeeping: Mapping[str, object] | None = item_bookkeeping(session, item_id)
    number = bookkeeping.get(WorkflowField.ISSUE_NUMBER) if bookkeeping is not None else None
    return snapshot, number if isinstance(number, int) else None, republication_progress(session, item_id)


def _record_save(session: Session, item_id: str, name: str, version_id: int, digest: str, artifact_number: int) -> bool:
    """Record an acknowledged save and end any pause: a save went through.

    An item no longer pending was retired meanwhile, so the save is no progress and nothing is recorded.
    """
    if not republication_pending(session, item_id):
        return False
    save_republication_progress(session, item_id, name, version_id, digest, artifact_number)
    save_republication_wait(session, RepublicationWait(None, 0))
    return True
