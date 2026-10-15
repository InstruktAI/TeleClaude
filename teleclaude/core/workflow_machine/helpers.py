"""The helpers a holding driver starts: the start is recorded on the item before the session is created.

``local/projects/teleclaude/spec/feature/workflow/item-lifecycle`` (Helpers of a driver). A start is a conditional
write on the item row: it is refused for a session that is not the item's holder and for a claim that is closing, so a
release that lands while a start is deciding wins. The record names the start before the session exists; once the
session is created the record names it, and a failed creation withdraws the record, so the closing sweep never waits
on a start that cannot finish.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from teleclaude.core.db import db
from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.process_identity import ProcessState, probe_process, start_identity
from teleclaude.core.workflow_machine.caller import group_sessions_of, in_claiming_group
from teleclaude.core.workflow_store.store import get_workflow_store
from teleclaude.core.workflow_store.types import ItemChange
from teleclaude.events.envelope import occurrence_id
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY
from teleclaude.types.todos import TodoState
from teleclaude.types.workflow_record import Act, HelperStart, WorkflowRecord

NOT_HOLDER = "{item}: only the session that holds it starts a helper"
CLOSING = "{item}: its claim is closing, so no helper is started"
EARLIER_GROUP = (
    "{item}: session {session} belongs to an earlier claim, so it starts no session; it is the overseer's to resolve"
)
ANCESTOR_WALK_CAP = 32
NO_IDENTITY = "{item}: the creating process cannot be named, so a helper start cannot be recorded"
UNKNOWN_ITEM = "no item {item} in this project"
START_ACT = "helper-start"


class HelperStartRefused(Exception):
    """A helper start was refused for one named cause; nothing was written."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def unsettled_helper_starts(record: WorkflowRecord) -> list[HelperStart]:
    """The recorded helper starts that name no session and whose creating process may still run.

    Time is no evidence that a creation ended. The creation runs in the process that recorded the start, so only that
    process's end proves it can never produce a session; a start whose process is gone is settled, and a session it
    created is found by the listing of the holder's group. Only positive evidence settles a start: one whose process
    cannot be named, or whose probe could not read it, stays unsettled.
    """
    return [
        start
        for start in record.helper_starts
        if not start.session_id
        and (not start.owner_identity or probe_process(start.owner_pid, start.owner_identity) is not ProcessState.ENDED)
    ]


def _same_project(session_project: str | None, project_root: str) -> bool:
    """Whether a session's project path is the project root, compared as resolved paths."""
    return bool(session_project) and Path(str(session_project)).resolve() == Path(project_root).resolve()


async def _works_on(session_id: str, item: str, project_root: str) -> bool:
    """Whether the session, or a session it descends from, works on the item of this project (persisted slug and path)."""
    current = session_id
    for _ in range(ANCESTOR_WALK_CAP):
        session = await db.get_session(current)
        if session is None:
            return False
        if session.working_slug == item and _same_project(session.project_path, project_root):
            return True
        if not session.initiator_session_id:
            return False
        current = session.initiator_session_id
    return False


async def _previous_machine_helpers(item: str, project_root: str, current: set[str]) -> list[str]:
    """Live sessions a claim the previous machine made left running, found by their persisted working slug and path.

    A claim recorded before this vocabulary left no ledger act. A session that something started, outside the current
    holder's group, and that works on this project's item or descends from a session that does, is what such a claim
    left running. A session a person opened themselves is not among them.
    """
    found: list[str] = []
    for session in await db.list_sessions(all_open=True):
        if session.session_id in current or not session.initiator_session_id:
            continue
        if await _works_on(session.session_id, item, project_root):
            found.append(session.session_id)
    return found


async def earlier_claim_sessions(
    record: WorkflowRecord, holder: str, item: str = "", project_root: str = ""
) -> tuple[str, ...]:
    """The live sessions of every earlier claiming group the item records, outside the current holder's group.

    A claiming group is the claimer and every session started from it, transitively. The earlier claims are the ones
    the item's ledger records and the holders its claim changes have displaced, which includes a claim the previous
    machine made without any ledger act, and (with the item and its project named) the sessions such a claim left
    running, found by their persisted working slug and project; the current holder, the sessions it started and sessions
    already closed are not among them.
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
    if item and project_root:
        legacy = await _previous_machine_helpers(item, project_root, current)
        found.extend(member for member in legacy if member not in found)
    return tuple(found)


async def register_helper_start(project_root: str, item: str, caller_session_id: str) -> str:
    """Record the start on the item, in one conditional write, and return its key."""
    store = await get_workflow_store(project_root)
    item_id = store.resolve_store_address_sync(item)
    keys: list[str] = []
    owner_identity = start_identity(os.getpid())
    if not owner_identity:
        raise HelperStartRefused(NO_IDENTITY.format(item=item))

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
            HelperStart(
                key=key,
                epoch=record.claim_epoch,
                requested_at=_now(),
                owner_pid=os.getpid(),
                owner_identity=owner_identity,
            )
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
    """Record a session creation as a helper start of every item whose holder's group the creator belongs to.

    This is the common creation boundary, so it covers every session started from a holder, transitively. The governing
    items come from authoritative evidence of the initiator's own chain (each ancestor's persisted working slug and
    project), not only from the directory the new session asks for, and the new session's own slug is one more
    candidate. For each item whose holder the creator is, or descends from, the start is recorded in a conditional write
    before the session exists; a closing claim or a changed holder refuses the creation. A creator in the group of an
    earlier claim is refused. The records name the created session, or are withdrawn when none was created.
    """
    fence = HelperFence()
    keys: list[tuple[str, str, str]] = []
    try:
        if initiator_session_id:
            for root, item in await _governing_items(project_root, working_slug, initiator_session_id):
                key = await _register_for_group(root, item, initiator_session_id)
                if key:
                    keys.append((root, item, key))
        yield fence
    except BaseException:
        for root, item, key in keys:
            await settle_helper_start(root, item, key, "")
        raise
    for root, item, key in keys:
        await settle_helper_start(root, item, key, fence.session_id)


async def _governing_items(
    project_root: str, working_slug: str | None, initiator_session_id: str
) -> list[tuple[str, str]]:
    """The (project root, item) pairs a creation may concern: the new session's slug, then each ancestor's own."""
    pairs: list[tuple[str, str]] = [(project_root, working_slug)] if working_slug else []
    current = initiator_session_id
    seen: set[str] = set()
    for _ in range(ANCESTOR_WALK_CAP):
        session = await db.get_session(current) if current and current not in seen else None
        if session is None:
            break
        seen.add(current)
        if session.working_slug and session.project_path:
            pair = (str(session.project_path), str(session.working_slug))
            if pair not in pairs:
                pairs.append(pair)
        current = session.initiator_session_id or ""
    return pairs


async def _register_for_group(project_root: str, item: str, initiator_session_id: str) -> str:
    """Register the start when the creator is in the item's holder's group; refuse it when in an earlier group's."""
    try:
        store = await get_workflow_store(project_root)
    except (OSError, ValueError):
        return ""
    raw = await store.read_state(item)
    if raw is None:
        return ""
    state = TodoState.model_validate(raw)
    holder = state.active_runner or ""
    if holder and await in_claiming_group(initiator_session_id, holder):
        return await register_helper_start(project_root, item, holder)
    if initiator_session_id in await earlier_claim_sessions(state.workflow, holder, item, project_root):
        raise HelperStartRefused(EARLIER_GROUP.format(item=item, session=initiator_session_id))
    return ""
