"""Stage issue reflections in the committing transaction and dispatch them once the commit lands."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

from instrukt_ai_logging import get_logger
from sqlalchemy.orm import Session

from teleclaude.core.todos_db._adapter import TodosDb
from teleclaude.core.todos_db._github_pull_requests import (
    PullRequestBookkeeping,
    mark_pull_request_owed,
    owed_pull_requests,
    pull_request_bookkeeping,
    store_pull_request_bookkeeping,
)
from teleclaude.core.todos_db._working_copy import (
    WorkingCopyField,
    WorkingCopyItemSnapshot,
    clear_reflection_owed,
    issue_relations,
    item_bookkeeping,
    item_snapshot,
    item_unverifiable,
    save_issue_projection_digest,
)
from teleclaude.core.todos_db._write_admission import (
    WRITE_ADMISSION_BUDGET_S,
    WorkingCopyWriteRefused,
    connect_admitted,
)
from teleclaude.core.workflow_store import github_reflection as _github_reflection
from teleclaude.core.workflow_store.github_io import GitHubWorkflowIO
from teleclaude.core.workflow_store.github_io_transport import failure_reason
from teleclaude.core.workflow_store.github_pull_request_apply import apply_pull_request
from teleclaude.core.workflow_store.github_pull_request_io import GitHubPullRequestIO
from teleclaude.core.workflow_store.github_pull_request_reflection import (
    PullRequestReflection,
    reflect_pull_request,
)
from teleclaude.core.workflow_store.github_question_projection import waiting_person_handles
from teleclaude.core.workflow_store.github_reflection import parse_projection_digests

_REFLECTIONS_KEY = "github_store_reflections"
_PULL_REQUESTS_KEY = "github_store_pull_request_reflections"
_PULL_REQUEST_QUEUE_FAILED = "github_store_pull_request_queue_failed"
_PULL_REQUEST_DERIVE_FAILED = "github_store_pull_request_derive_failed"
_PULL_REQUEST_FAILED = "github_store_pull_request_failed"
_PULL_REQUEST_REPAIR_FAILED = "github_store_pull_request_repair_failed"
_PULL_REQUEST_STORE_FAILED = "github_store_pull_request_store_failed"
_REFLECTION_QUEUE_FAILED = "github_store_reflection_queued_failed"
_REFLECTION_FAILED = "github_store_reflection_failed"
_REFLECTION_STORE_FAILED = "github_store_reflection_store_failed"
_CLEAR_OWED_REFLECTION_SQL = "DELETE FROM github_owed_reflection WHERE item_id = ?"
_SAVE_PROJECTION_DIGEST_SQL = "UPDATE github_item SET projection_digest = ? WHERE item_id = ?"
_ACKNOWLEDGEMENT_THREAD = "teleclaude-github-acknowledgements"
logger = get_logger(__name__)
# One process-wide thread keeps an item's acknowledgements in order and keeps their writer waits off every event loop.
_acknowledgements = ThreadPoolExecutor(max_workers=1, thread_name_prefix=_ACKNOWLEDGEMENT_THREAD)


def acknowledge_off_loop(work: Callable[..., None], *arguments: Any) -> None:
    """Run a completed reflection's bookkeeping on the acknowledgement thread, off every event loop."""
    _acknowledgements.submit(work, *arguments)


def stage_issue_reflections(
    session: Session, reflection_rows: list[tuple[int, str, WorkingCopyItemSnapshot]]
) -> frozenset[str]:
    """Derive each row's issue reflection inside the committing transaction and hold it for dispatch.

    A reflection that changes nothing on GitHub needs no write, so its acknowledgement is recorded here, in
    the transaction that established the projection: the digest is saved and the owed marker cleared before
    any later commit can mark the item owed again. Returns the items settled this way.
    """
    projections: list[_github_reflection.ProjectionQueueEntry] = []
    settled: set[str] = set()
    for issue_number, item_id, snapshot in reflection_rows:
        bookkeeping = item_bookkeeping(session, item_id)
        issue_id = _int_or_none(bookkeeping.get(WorkingCopyField.ISSUE_ID)) if bookkeeping else None
        relations = issue_relations(session, snapshot, {})
        reflection = _github_reflection.reflect_issue(
            snapshot,
            parent_issue_number=relations.parent_issue_number,
            parent_issue_id=relations.parent_issue_id,
            blocked_by_issue_ids=relations.blocked_by_issue_ids,
            waiting_assignees=waiting_person_handles(session, item_id, snapshot),
        )
        previous = parse_projection_digests((bookkeeping or {}).get(WorkingCopyField.PROJECTION_DIGEST))
        changed = _github_reflection.changed_projection_parts(reflection, previous)
        digest = _github_reflection.serialize_projection_digests(reflection.projection_digests)
        if issue_id is not None and not changed:
            save_issue_projection_digest(session, item_id, digest)
            clear_reflection_owed(session, item_id)
            settled.add(item_id)
            continue
        projections.append((issue_number, issue_id, item_id, reflection, changed, digest))
    session.info[_REFLECTIONS_KEY] = projections
    return frozenset(settled)


def dispatch_staged_reflections(session: Session, db_path: Path, io: GitHubWorkflowIO) -> None:
    """Queue the reflections staged for this commit; each acknowledges itself when GitHub accepted it."""
    reflections = session.info.pop(_REFLECTIONS_KEY, [])
    for issue_number, issue_id, item_id, reflection, changed, digest in reflections:
        if issue_id is None:
            continue
        try:
            future = io.queue_reflection(issue_number, issue_id, reflection, changed)
            future.add_done_callback(partial(_reflection_finished, db_path, item_id, digest))
        except Exception as error:
            logger.warning(
                _REFLECTION_QUEUE_FAILED,
                item_id=item_id,
                reason=type(error).__name__,
                exc_info=True,
            )


def _reflection_finished(db_path: Path, item_id: str, projection_digest: str, future: Future[Any]) -> None:
    try:
        future.result()
    except Exception as error:
        logger.warning(
            _REFLECTION_FAILED,
            item_id=item_id,
            reason=type(error).__name__,
            exc_info=True,
        )
        return
    # Runs on the GitHub I/O loop thread: the write waits for the writer on the acknowledgement thread instead.
    _acknowledgements.submit(_acknowledge_reflection, db_path, item_id, projection_digest)


def _acknowledge_reflection(db_path: Path, item_id: str, projection_digest: str) -> None:
    try:
        _store_projection_reflection(db_path, item_id, projection_digest)
    except (sqlite3.Error, WorkingCopyWriteRefused) as error:
        # The digest update and the owed-row delete share one transaction, so the item stays owed and refresh repairs it.
        logger.warning(_REFLECTION_STORE_FAILED, item_id=item_id, reason=type(error).__name__, exc_info=True)


def _store_projection_reflection(db_path: Path, item_id: str, projection_digest: str) -> None:
    connection = connect_admitted(str(db_path), WRITE_ADMISSION_BUDGET_S)
    try:
        connection.execute(_SAVE_PROJECTION_DIGEST_SQL, (projection_digest, item_id))
        connection.execute(_CLEAR_OWED_REFLECTION_SQL, (item_id,))
        connection.commit()
    finally:
        connection.close()


def _int_or_none(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    return None


def stage_pull_request_reflections(
    session: Session, reflection_rows: list[tuple[int, str, WorkingCopyItemSnapshot]]
) -> None:
    """Derive each row's pull request inside the committing transaction and mark the ones that owe a write."""
    staged: list[tuple[str, PullRequestReflection, PullRequestBookkeeping]] = []
    for issue_number, item_id, snapshot in reflection_rows:
        unwritten = owe_unwritten_pull_request(session, item_id, issue_number, snapshot)
        if unwritten is not None:
            staged.append((item_id, *unwritten))
    session.info[_PULL_REQUESTS_KEY] = staged


def owe_unwritten_pull_request(
    session: Session, item_id: str, issue_number: int, snapshot: WorkingCopyItemSnapshot
) -> tuple[PullRequestReflection, PullRequestBookkeeping] | None:
    """Mark the item's pull request owed when GitHub is not known to hold what its record reflects.

    Serves the committing transaction and every path that restores a record without capturing a change
    (rebuild and refresh adoption): a restored item starts with empty bookkeeping, so it owes its pull
    request and refresh finds it, its reviews and its closure again. Returns the desired pull request and
    what is known of it, or None when nothing is owed.
    """
    try:
        desired = reflect_pull_request(snapshot, issue_number)
    except Exception as error:  # supervision boundary: a reflection never decides the operation's outcome
        logger.warning(_PULL_REQUEST_DERIVE_FAILED, item_id=item_id, reason=failure_reason(error), exc_info=True)
        mark_pull_request_owed(session, item_id)
        return None
    if desired is None:
        return None
    known = pull_request_bookkeeping(session, item_id)
    review_owed = any(review.round not in known.reviews for review in desired.reviews)
    if known.digest == desired.digest and not review_owed:
        return None
    if review_owed:
        # The committing snapshot holds only the versions not yet pushed; a review's findings may be older.
        complete = item_snapshot(session, item_id)
        desired = (reflect_pull_request(complete, issue_number) if complete is not None else None) or desired
    mark_pull_request_owed(session, item_id)
    return desired, known


def dispatch_staged_pull_requests(session: Session, db_path: Path, pull_requests: GitHubPullRequestIO) -> None:
    """Queue the pull requests staged for this commit, each as its own future with its own completion."""
    for item_id, desired, known in session.info.pop(_PULL_REQUESTS_KEY, []):
        try:
            future = pull_requests.submit(partial(_apply, desired, known))
            future.add_done_callback(partial(_pull_request_finished, db_path, item_id, known))
        except Exception as error:
            logger.warning(
                _PULL_REQUEST_QUEUE_FAILED,
                item_id=item_id,
                reason=failure_reason(error),
                exc_info=True,
            )


async def repair_owed_pull_requests(store: TodosDb, pull_requests: GitHubPullRequestIO, blocked: set[str]) -> None:
    """Rewrite every owed pull request from its record; one item's failure never stops the rest.

    Runs in its own failure boundary, apart from the issue repair: a failure is logged with its cause
    and the pull request stays owed for the next refresh.
    """
    async with store._session() as read_session:
        owed = await read_session.run_sync(owed_pull_requests)
    for item_id in owed:
        if item_id in blocked:
            continue
        try:
            await _repair_pull_request(store, pull_requests, item_id)
        except Exception as error:  # supervision boundary: a failed pull request stays owed
            logger.warning(
                _PULL_REQUEST_REPAIR_FAILED,
                item_id=item_id,
                reason=failure_reason(error),
                exc_info=True,
            )


async def _repair_pull_request(store: TodosDb, pull_requests: GitHubPullRequestIO, item_id: str) -> None:
    def read(session: Session) -> tuple[WorkingCopyItemSnapshot | None, int | None, PullRequestBookkeeping, bool]:
        bookkeeping = item_bookkeeping(session, item_id)
        issue_number = _int_or_none(bookkeeping.get(WorkingCopyField.ISSUE_NUMBER)) if bookkeeping else None
        return (
            item_snapshot(session, item_id),
            issue_number,
            pull_request_bookkeeping(session, item_id),
            item_unverifiable(session, item_id),
        )

    async with store._session() as read_session:
        snapshot, issue_number, known, unverifiable = await read_session.run_sync(read)
    if snapshot is None or issue_number is None or unverifiable:
        return
    desired = reflect_pull_request(snapshot, issue_number)
    db_path = Path(store.db_path)
    if desired is None:
        await asyncio.to_thread(store_pull_request_bookkeeping, db_path, item_id, known, owed=False)
        return
    try:
        await asyncio.wrap_future(pull_requests.submit(partial(_apply, desired, known)))
    except BaseException:
        await asyncio.to_thread(store_pull_request_bookkeeping, db_path, item_id, known, owed=True)
        raise
    await asyncio.to_thread(store_pull_request_bookkeeping, db_path, item_id, known, owed=False)


async def _apply(desired: PullRequestReflection, known: PullRequestBookkeeping, io: GitHubPullRequestIO) -> None:
    await apply_pull_request(io, desired, known)


def _pull_request_finished(db_path: Path, item_id: str, known: PullRequestBookkeeping, future: Future[Any]) -> None:
    owed = False
    try:
        future.result()
    except Exception as error:
        owed = True
        logger.warning(
            _PULL_REQUEST_FAILED,
            item_id=item_id,
            reason=failure_reason(error),
            exc_info=True,
        )
    # Runs on the GitHub I/O loop thread: the write waits for the writer on the acknowledgement thread instead.
    _acknowledgements.submit(_acknowledge_pull_request, db_path, item_id, known, owed)


def _acknowledge_pull_request(db_path: Path, item_id: str, known: PullRequestBookkeeping, owed: bool) -> None:
    try:
        store_pull_request_bookkeeping(db_path, item_id, known, owed=owed)
    except (sqlite3.Error, WorkingCopyWriteRefused) as error:
        logger.warning(_PULL_REQUEST_STORE_FAILED, item_id=item_id, reason=type(error).__name__, exc_info=True)
