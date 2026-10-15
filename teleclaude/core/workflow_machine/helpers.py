"""The helpers a holding driver starts: the start is recorded on the item before the session is created.

``local/projects/teleclaude/spec/feature/workflow/item-lifecycle`` (Helpers of a driver). A start is a conditional
write on the item row: it is refused for a session that is not the item's holder and for a claim that is closing, so a
release that lands while a start is deciding wins. The record names the start before the session exists; once the
session is created the record names it, and a failed creation withdraws the record, so the closing sweep never waits
on a start that cannot finish.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from teleclaude.core.db import db
from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.process_identity import boot_session
from teleclaude.core.workflow_machine.caller import group_sessions_of, in_claiming_group
from teleclaude.core.workflow_store.store import get_workflow_store
from teleclaude.core.workflow_store.types import ItemChange
from teleclaude.events.envelope import occurrence_id
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY
from teleclaude.types.todos import TodoState
from teleclaude.types.workflow_record import Act, HelperStart, WorkflowRecord

NOT_HOLDER = "{item}: only the session that holds it starts a helper"
CLOSING = "{item}: its claim is closing, so no helper is started"
UNKNOWN_ITEM = "no item {item} in this project"
START_ACT = "helper-start"


class HelperStartRefused(Exception):
    """A helper start was refused for one named cause; nothing was written."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def earlier_claim_sessions(record: WorkflowRecord, holder: str) -> tuple[str, ...]:
    """The live sessions of every earlier claiming group the item records, outside the current holder's group.

    A claiming group is the claimer and every session started from it, transitively. The earlier claims are the ones
    the item's ledger records and the holders its claim changes have displaced, which includes a claim the previous
    machine made without any ledger act; the current holder, the sessions it started and sessions already closed are not among
    them.
    """
    current = {holder, *await group_sessions_of(holder)} if holder else set()
    found: list[str] = []
    recorded = [entry.session_id for entry in record.ledger if entry.act is Act.CLAIM]
    for claimer in dict.fromkeys([*recorded, *record.claimers]):
        if not claimer or claimer in current:
            continue
        session = await db.get_session(claimer)
        members = [*(await group_sessions_of(claimer)), *([claimer] if session and session.closed_at is None else [])]
        found.extend(member for member in members if member not in current and member not in found)
    return tuple(found)


async def register_helper_start(project_root: str, item: str, caller_session_id: str) -> str:
    """Record the start on the item, in one conditional write, and return its key."""
    store = await get_workflow_store(project_root)
    item_id = store.resolve_store_address_sync(item)
    keys: list[str] = []

    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        if current is None or item_id is None:
            raise HelperStartRefused(UNKNOWN_ITEM.format(item=item))
        state = TodoState.model_validate(current)
        if state.active_runner != caller_session_id:
            raise HelperStartRefused(NOT_HOLDER.format(item=item))
        if state.workflow.closing:
            raise HelperStartRefused(CLOSING.format(item=item))
        record = state.workflow.model_copy(deep=True)
        key = occurrence_id(
            project_root, item_id, START_ACT, str(record.claim_epoch), str(len(record.helper_starts)), _now()
        )
        record.helper_starts.append(
            HelperStart(key=key, epoch=record.claim_epoch, requested_at=_now(), boot=boot_session())
        )
        keys.append(key)
        return ItemChange(state={**current, WORKFLOW_STATE_KEY: record.to_state()})

    await store.commit_item_change(item, expect_digests={}, mutate=mutate, updated_by=caller_session_id)
    return keys[0]


async def settle_helper_start(project_root: str, item: str, key: str, session_id: str) -> None:
    """Name the session the start created, or withdraw the start when none was created (empty session id)."""
    store = await get_workflow_store(project_root)

    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        if current is None:
            return None
        record = TodoState.model_validate(current).workflow.model_copy(deep=True)
        if not any(start.key == key for start in record.helper_starts):
            return None
        if session_id:
            record.helper_starts = [
                start.model_copy(update={"session_id": session_id}) if start.key == key else start
                for start in record.helper_starts
            ]
        else:
            record.helper_starts = [start for start in record.helper_starts if start.key != key]
        return ItemChange(state={**current, WORKFLOW_STATE_KEY: record.to_state()})

    await store.commit_item_change(item, expect_digests={}, mutate=mutate, updated_by=None)


class HelperFence:
    """The outcome of a creation inside a helper-start fence: the session it created, once there is one."""

    def __init__(self) -> None:
        self.session_id = ""

    def named(self, session_id: str) -> None:
        """Record the session the creation produced."""
        self.session_id = session_id


@asynccontextmanager
async def helper_start_fence(
    project_root: str, working_slug: str | None, initiator_session_id: str | None
) -> AsyncIterator[HelperFence]:
    """Record a session creation as a helper start when it is made from the group of an item's holder.

    This is the common creation boundary, so it covers every session started from the holder, transitively, not only
    the declared child: the item named by the new session's working slug is read, and when the resolved initiator is
    the holder or descends from it, the start is recorded on the item in a conditional write before the session is
    created. A closing claim or a holder who changed refuses the creation. The record names the created session, or is
    withdrawn when none was created.
    """
    fence = HelperFence()
    key = ""
    if working_slug and initiator_session_id:
        store = await get_workflow_store(project_root)
        raw = await store.read_state(working_slug)
        holder = TodoState.model_validate(raw).active_runner if raw is not None else None
        if holder and await in_claiming_group(initiator_session_id, holder):
            key = await register_helper_start(project_root, working_slug, holder)
    try:
        yield fence
    except BaseException:
        if key:
            await settle_helper_start(project_root, working_slug or "", key, "")
        raise
    if key:
        await settle_helper_start(project_root, working_slug or "", key, fence.session_id)
