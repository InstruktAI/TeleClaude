"""Stage board reflections in the committing transaction and dispatch them once the commit lands.

The board is owed apart from the issue and the pull request: a failure of any one never holds back the others.
A board write that fails is logged and stays owed in working-copy bookkeeping; the store's next refresh and a
repair write it again. A board that is not yet recorded owes every item without a GitHub call.
"""

from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import Future
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from instrukt_ai_logging import get_logger
from sqlalchemy.orm import Session

from teleclaude.core.todos_db._adapter import TodosDb
from teleclaude.core.todos_db._github_board import (
    BoardItemBookkeeping,
    BoardTargets,
    board_item_bookkeeping,
    board_setup,
    clear_board_item_owed,
    mark_board_item_owed,
    mark_board_item_owed_at,
    owed_board_items,
    store_board_item,
)
from teleclaude.core.todos_db._working_copy import (
    WorkingCopyField,
    WorkingCopyItemSnapshot,
    item_bookkeeping,
    item_snapshot,
    item_unverifiable,
)
from teleclaude.core.workflow_store.github_board_io import GitHubBoardIO
from teleclaude.core.workflow_store.github_board_reflection import BoardItemReflection, reflect_board_item
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused, failure_reason
from teleclaude.core.workflow_store.github_reflection_queue import owe_unwritten_pull_request

_BOARD_ITEMS_KEY = "github_store_board_reflections"
_QUEUE_FAILED = "github_store_board_queue_failed"
_DERIVE_FAILED = "github_store_board_derive_failed"
_FAILED = "github_store_board_failed"
_REPAIR_FAILED = "github_store_board_repair_failed"
_STORE_FAILED = "github_store_board_store_failed"
logger = get_logger(__name__)


@dataclass(frozen=True)
class StagedBoardItem:
    """One item's board write: what it should be, what is known of it and where to address it."""

    item_id: str
    node_id: str
    desired: BoardItemReflection | None
    known: BoardItemBookkeeping
    targets: BoardTargets


def stage_board_reflections(session: Session, reflection_rows: list[tuple[int, str, WorkingCopyItemSnapshot]]) -> None:
    """Derive each row's board item inside the committing transaction and mark the ones that owe a write."""
    targets = board_setup(session).targets()
    staged: list[StagedBoardItem] = []
    for _issue_number, item_id, snapshot in reflection_rows:
        item = owe_unwritten_board_item(session, item_id, snapshot, targets)
        if item is not None:
            staged.append(item)
    session.info[_BOARD_ITEMS_KEY] = staged


def owe_unwritten_board_item(
    session: Session, item_id: str, snapshot: WorkingCopyItemSnapshot, targets: BoardTargets | None
) -> StagedBoardItem | None:
    """Mark the item's board item owed when GitHub is not known to hold what its record reflects.

    Returns the write to dispatch after the commit, or None when nothing is owed or the board cannot be
    addressed yet, in which case the item stays owed for the refresh that records the board.
    """
    try:
        desired = reflect_board_item(snapshot)
    except Exception as error:  # supervision boundary: a reflection never decides the operation's outcome
        logger.warning(_DERIVE_FAILED, item_id=item_id, reason=failure_reason(error), exc_info=True)
        mark_board_item_owed(session, item_id)
        return None
    known = board_item_bookkeeping(session, item_id)
    if desired is None and known.board_item_id is None:
        clear_board_item_owed(session, item_id)
        return None
    if desired is not None and known.board_item_id is not None and known.digest == desired.digest:
        return None
    mark_board_item_owed(session, item_id)
    node_id = _issue_node_id(session, item_id)
    if targets is None or node_id is None:
        return None
    return StagedBoardItem(item_id=item_id, node_id=node_id, desired=desired, known=known, targets=targets)


def owe_restored_item(session: Session, item_id: str, issue_number: int, snapshot: WorkingCopyItemSnapshot) -> None:
    """Owe a restored item's pull request and board item together.

    Rebuild and refresh adoption restore records without capturing a change, so a restored item starts with
    empty bookkeeping and owes both reflections; a removed item's board item is deleted by the same repair.
    """
    owe_unwritten_pull_request(session, item_id, issue_number, snapshot)
    mark_board_item_owed(session, item_id)


def dispatch_staged_board_items(session: Session, db_path: Path, board: GitHubBoardIO) -> None:
    """Queue the board items staged for this commit, each as its own future with its own completion."""
    for item in session.info.pop(_BOARD_ITEMS_KEY, []):
        try:
            future = board.submit(partial(_apply, item))
            future.add_done_callback(partial(_finished, db_path, item.item_id))
        except Exception as error:
            logger.warning(_QUEUE_FAILED, item_id=item.item_id, reason=failure_reason(error), exc_info=True)


async def repair_owed_board_items(
    store: TodosDb, board: GitHubBoardIO, blocked: set[str], *, force: bool = False
) -> list[tuple[str, str]]:
    """Write every owed board item from its record; one item's failure never stops the rest.

    Returns each item left owed with its cause. A write is skipped when the board already shows the item as
    its record reflects, unless `force` is set, which a repair uses to undo hand edits the digest cannot see.
    """
    async with store._session() as read_session:
        owed = await read_session.run_sync(owed_board_items)
    left: list[tuple[str, str]] = []
    for item_id in owed:
        if item_id in blocked:
            continue
        try:
            await _repair_item(store, board, item_id, force)
        except Exception as error:  # supervision boundary: a failed board item stays owed
            logger.warning(_REPAIR_FAILED, item_id=item_id, reason=failure_reason(error), exc_info=True)
            left.append((item_id, failure_reason(error)))
    return left


async def _repair_item(store: TodosDb, board: GitHubBoardIO, item_id: str, force: bool) -> None:
    def read(
        session: Session,
    ) -> tuple[WorkingCopyItemSnapshot | None, str | None, BoardItemBookkeeping, BoardTargets | None, bool]:
        bookkeeping = item_bookkeeping(session, item_id)
        return (
            item_snapshot(session, item_id),
            _text_or_none(bookkeeping.get(WorkingCopyField.NODE_ID)) if bookkeeping else None,
            board_item_bookkeeping(session, item_id),
            board_setup(session).targets(),
            item_unverifiable(session, item_id),
        )

    async with store._session() as read_session:
        snapshot, node_id, known, targets, unverifiable = await read_session.run_sync(read)
    if snapshot is None or unverifiable or targets is None:
        return
    db_path = Path(store.db_path)
    desired = reflect_board_item(snapshot)
    if desired is None and known.board_item_id is None:
        store_board_item(db_path, item_id, None, owed=False)
        return
    if not force and desired is not None and known.board_item_id is not None and known.digest == desired.digest:
        store_board_item(db_path, item_id, known, owed=False)
        return
    if node_id is None:
        return
    item = StagedBoardItem(item_id=item_id, node_id=node_id, desired=desired, known=known, targets=targets)
    result = await asyncio.wrap_future(board.submit(partial(_apply, item)))
    store_board_item(db_path, item_id, result, owed=False)


async def _apply(item: StagedBoardItem, io: GitHubBoardIO) -> BoardItemBookkeeping | None:
    """Make the board show the item as its record reflects; None means the item has no board item."""
    targets = item.targets
    if item.desired is None:
        if item.known.board_item_id is not None:
            try:
                await io.delete_item(targets.project_id, item.known.board_item_id)
            except GitHubIORefused as refused:
                if refused.reason is not GitHubIOFailure.NOT_FOUND:
                    raise
        return None
    board_item_id = item.known.board_item_id or await io.add_item(targets.project_id, item.node_id)
    try:
        await _write_fields(io, targets, item.desired, board_item_id)
    except GitHubIORefused as refused:
        # An item someone deleted by hand is added again; any other refusal leaves the item owed.
        if refused.reason is not GitHubIOFailure.NOT_FOUND or item.known.board_item_id is None:
            raise
        board_item_id = await io.add_item(targets.project_id, item.node_id)
        await _write_fields(io, targets, item.desired, board_item_id)
    return BoardItemBookkeeping(board_item_id=board_item_id, digest=item.desired.digest)


async def _write_fields(
    io: GitHubBoardIO, targets: BoardTargets, desired: BoardItemReflection, board_item_id: str
) -> None:
    await io.set_item_option(
        targets.project_id, board_item_id, targets.status_field_id, targets.lane_option_ids[desired.lane]
    )
    if desired.needs_you:
        await io.set_item_option(
            targets.project_id, board_item_id, targets.needs_you_field_id, targets.needs_you_option_id
        )
    else:
        await io.clear_item_field(targets.project_id, board_item_id, targets.needs_you_field_id)


def _finished(db_path: Path, item_id: str, future: Future[Any]) -> None:
    try:
        result = future.result()
    except Exception as error:
        logger.warning(_FAILED, item_id=item_id, reason=failure_reason(error), exc_info=True)
        _keep_owed(db_path, item_id)
        return
    try:
        store_board_item(db_path, item_id, result, owed=False)
    except sqlite3.Error as error:
        # The item stays owed, so refresh writes it again.
        logger.warning(_STORE_FAILED, item_id=item_id, reason=type(error).__name__, exc_info=True)


def _keep_owed(db_path: Path, item_id: str) -> None:
    """Re-mark the item owed: a newer write may have cleared the marker while this one was in flight."""
    try:
        mark_board_item_owed_at(db_path, item_id)
    except sqlite3.Error as error:
        logger.warning(_STORE_FAILED, item_id=item_id, reason=type(error).__name__, exc_info=True)


def _issue_node_id(session: Session, item_id: str) -> str | None:
    bookkeeping = item_bookkeeping(session, item_id)
    return _text_or_none(bookkeeping.get(WorkingCopyField.NODE_ID)) if bookkeeping else None


def _text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
