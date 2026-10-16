"""The helpers a holding driver starts: the start is recorded on the item before the session is created.

``local/projects/teleclaude/spec/feature/workflow/item-lifecycle`` (Helpers of a driver). A start is a conditional
write on the item row: it is refused for a session that is not the item's holder and for a claim that is closing, so a
release that lands while a start is deciding wins. The record names the start before the session exists; once the
session is created the record names it, and a failed creation withdraws the record, so the closing sweep never waits
on a start that cannot finish.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from teleclaude.config.machine import config
from teleclaude.core.db import db
from teleclaude.core.models import Session
from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.operation_caller_identity import relayed_caller_computer
from teleclaude.core.process_identity import ProcessState, probe_process, start_identity
from teleclaude.core.session_utils import cached_remote_session
from teleclaude.core.workflow_machine.caller import group_view_of, in_claiming_group
from teleclaude.core.workflow_machine.peer_starts import StartEntry, register_with_owner, settle_with_owners
from teleclaude.core.workflow_store.store import get_workflow_store
from teleclaude.core.workflow_store.types import ItemChange
from teleclaude.events.envelope import occurrence_id
from teleclaude.events.references import EventRef, ReferenceKind
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY
from teleclaude.types.procedure_delivery import BINDING_SECTION, BindingField
from teleclaude.types.todos import TodoState
from teleclaude.types.workflow_record import Act, HelperStart, RemoteMember, WorkflowRecord

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
    A retained remote member of an earlier group whose computer could not say whether it ended counts as one: the group
    is not shown ended, so the entry refuses until it is.
    """
    retained = record.remote_members
    current = {holder, *(m.session_id for m in (await group_view_of(holder, retained)).live)} if holder else set()
    found: list[str] = []
    recorded = [entry.session_id for entry in record.ledger if entry.act is Act.CLAIM]
    for claimer in dict.fromkeys([*recorded, *record.claimers]):
        if not claimer or claimer in current:
            continue
        session = await db.get_session(claimer)
        earlier_view = await group_view_of(claimer, retained)
        earlier = [*(m.session_id for m in earlier_view.live), *earlier_view.unresolved]
        members = [*earlier, *([claimer] if session and session.closed_at is None else [])]
        found.extend(member for member in members if member not in current and member not in found)
    if item and project_root:
        legacy = await _previous_machine_helpers(item, project_root, current)
        found.extend(member for member in legacy if member not in found)
    return tuple(found)


async def register_helper_start(project_root: str, item: str, caller_session_id: str, computer: str = "") -> str:
    """Record the start on the item, in one conditional write, and return its key.

    A start that will be created on another computer names it, so a start whose reply never came back still tells the
    sweep which computer to hear from before it concludes.
    """
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
                computer=computer,
            )
        )
        keys.append(key)
        return ItemChange(state={**current, WORKFLOW_STATE_KEY: record.to_state()})

    await store.commit_item_change(item, expect_digests={}, mutate=mutate, updated_by=caller_session_id)
    return keys[0]


async def settle_helper_start(
    project_root: str, item: str, key: str, session_id: str, remote: RemoteMember | None = None
) -> None:
    """Name the session the start created, or withdraw the start when none was created (empty session id).

    A session created on another computer is retained as a remote member in the same write that names it, so the
    sweep finds it from the item alone.
    """
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
            if remote is not None and all(member.session_id != remote.session_id for member in record.remote_members):
                record.remote_members = [*record.remote_members, remote]
        else:
            record.helper_starts = [start for start in record.helper_starts if start.key != key]
        return ItemChange(state={**current, WORKFLOW_STATE_KEY: record.to_state()})

    await store.commit_item_change(item, expect_digests={}, mutate=mutate, updated_by=None)


class HelperFence:
    """The outcome of a creation inside a helper-start fence: the session it created, once there is one."""

    def __init__(self, computer: str = "") -> None:
        self.session_id = ""
        self.computer = computer
        self.ambiguous = False

    def named(self, session_id: str) -> None:
        """Record the session the creation produced."""
        self.session_id = session_id

    def may_have_created(self) -> None:
        """Mark the creation as one whose outcome is not known: its start stays recorded and is never withdrawn."""
        self.ambiguous = True

    def refused(self) -> None:
        """Mark the creation as definitely not made: the start is withdrawn."""
        self.ambiguous = False


@asynccontextmanager
async def helper_start_fence(
    project_root: str, working_slug: str | None, initiator_session_id: str | None, computer: str = ""
) -> AsyncIterator[HelperFence]:
    """Record a session creation as a helper start of every item whose holder\'s group the creator belongs to.

    This is the common creation boundary, so it covers every session started from a holder, transitively. The governing
    items come from authoritative evidence of the creator\'s own chain (each ancestor\'s persisted working slug and
    project), not only from the directory the new session asks for, and the new session\'s own slug is one more
    candidate. A chain that leaves this computer continues on the computer that holds the next ancestor, which records
    the start on its own items. For each item whose holder the creator is, or descends from, the start is recorded in a
    conditional write before the session exists; a closing claim or a changed holder refuses the creation. A creator in
    the group of an earlier claim is refused. The records name the created session, or are withdrawn when none was
    created. ``computer`` names the computer the session is created on when it is not this one.
    """
    fence = HelperFence(computer)
    local = config.computer.name
    entries = (
        await register_for_creation(project_root, working_slug, initiator_session_id, computer)
        if initiator_session_id
        else []
    )
    try:
        yield fence
    except BaseException:
        if not fence.ambiguous:
            await settle_entries(entries, "", computer or local, initiator_session_id or "")
        raise
    if fence.session_id or not fence.ambiguous:
        await settle_entries(entries, fence.session_id, computer or local, initiator_session_id or "")


@dataclass
class _Lineage:
    """What a creator\'s chain concerns: the items on this computer, and the ancestors held by other computers."""

    items: list[tuple[str, str]] = field(default_factory=list)
    remote: list[tuple[str, str]] = field(default_factory=list)


async def _creation_lineage(project_root: str, working_slug: str | None, start_session_id: str) -> _Lineage:
    """The (project root, item) pairs a creation may concern, and the ancestors that other computers hold.

    The new session\'s slug comes first, then each ancestor\'s own items. A creator that another computer carried here
    is not in this computer\'s store; its chain continues from the initiator its own computer recorded. An ancestor
    this computer does not hold, whose record names another computer, is handed to that computer.
    """
    lineage = _Lineage(items=[(project_root, working_slug)] if working_slug else [])
    local = config.computer.name
    current = start_session_id
    current_computer = ""
    seen: set[str] = set()
    for _ in range(ANCESTOR_WALK_CAP):
        if not current or current in seen:
            break
        seen.add(current)
        session = await db.get_session(current)
        if session is not None:
            for pair in _session_items(session):
                if pair not in lineage.items:
                    lineage.items.append(pair)
            current, current_computer = session.initiator_session_id or "", session.initiator_computer or ""
            continue
        carried = relayed_caller_computer(current) if current == start_session_id else None
        snapshot = cached_remote_session(current, carried) if carried else None
        if snapshot is not None:
            current, current_computer = snapshot.initiator_session_id or "", snapshot.initiator_computer or ""
            continue
        held_by = current_computer if current_computer and current_computer != local else ""
        if not held_by:
            open_ancestor = cached_remote_session(current)
            held_by = str(open_ancestor.computer) if open_ancestor is not None and open_ancestor.computer else ""
        if held_by and held_by != local:
            lineage.remote.append((current, held_by))
        break
    return lineage


async def register_for_creation(
    project_root: str, working_slug: str | None, initiator_session_id: str, computer: str
) -> list[StartEntry]:
    """Record the start on every governing item, here and on the computers that hold the creator\'s ancestors.

    Nothing stays recorded when any one record is refused: the starts already made are withdrawn first.
    """
    local = config.computer.name
    carried_from = relayed_caller_computer(initiator_session_id) or local
    entries: list[StartEntry] = []
    try:
        lineage = await _creation_lineage(project_root, working_slug, initiator_session_id)
        for root, item in lineage.items:
            key = await _register_for_group(root, item, initiator_session_id, computer, carried_from)
            if key:
                entries.append(StartEntry("", root, item, key))
        for ancestor, owner in lineage.remote:
            entries.extend(
                await register_with_owner(owner, initiator_session_id, carried_from, ancestor, computer or local)
            )
    except BaseException:
        await settle_entries(entries, "", computer or local, initiator_session_id)
        raise
    return entries


async def register_from_ancestor(
    creator_session_id: str, creator_computer: str, ancestor_session_id: str, new_computer: str
) -> list[StartEntry]:
    """Serve a start that another computer asks this one to record: the creator\'s chain reaches ``ancestor`` here.

    The creator is judged against the items found along the ancestor\'s chain on this computer\'s own evidence; the
    entries returned name this computer as the holder so the creator\'s computer settles them here.
    """
    local = config.computer.name
    elsewhere = new_computer if new_computer != local else ""
    entries: list[StartEntry] = []
    try:
        lineage = await _creation_lineage("", None, ancestor_session_id)
        for root, item in lineage.items:
            key = await _register_for_group(root, item, creator_session_id, elsewhere, creator_computer)
            if key:
                entries.append(StartEntry(local, root, item, key))
        for ancestor, owner in lineage.remote:
            entries.extend(
                await register_with_owner(owner, creator_session_id, creator_computer, ancestor, new_computer)
            )
    except BaseException:
        await settle_entries(entries, "", new_computer, creator_session_id)
        raise
    return entries


async def settle_entries(
    entries: Sequence[StartEntry], session_id: str, session_computer: str, creator_session_id: str
) -> None:
    """Name the created session on every recorded start, or withdraw the starts when none was created.

    A session created on another computer than the item\'s is retained as a remote member in the write that names it,
    parented to its creator; the computers that hold other starts settle them on their own request.
    """
    local = config.computer.name
    for entry in entries:
        if entry.computer and entry.computer != local:
            continue
        remote = (
            RemoteMember(session_id=session_id, computer=session_computer, parent=creator_session_id)
            if session_id and session_computer != local and creator_session_id
            else None
        )
        await settle_helper_start(entry.root, entry.item, entry.key, session_id, remote)
    await settle_with_owners(entries, session_id, session_computer, creator_session_id, local)


def _session_items(session: Session) -> list[tuple[str, str]]:
    """The items a session is persistently about: its working slug, and the item its procedure binding names.

    A driver the platform activated for an item has no working slug; the item is the structured binding\'s subject, and
    the project is the folder the session works in, which is the folder of the home the binding names. Raw command or
    title text is never read as evidence.
    """
    if not session.project_path:
        return []
    items: list[tuple[str, str]] = []
    if session.working_slug:
        items.append((str(session.project_path), str(session.working_slug)))
    binding = (session.origin_metadata or {}).get(BINDING_SECTION)
    subject = binding.get(BindingField.SUBJECT.value) if isinstance(binding, dict) else None
    if isinstance(subject, str) and subject:
        try:
            ref = EventRef.from_token(subject)
        except ValueError:
            return items
        if ref.kind == ReferenceKind.TODO.value:
            items.append((str(session.project_path), ref.identity))
    return items


async def _register_for_group(
    project_root: str, item: str, initiator_session_id: str, computer: str = "", creator_computer: str = ""
) -> str:
    """Register the start when the creator is in the item\'s holder\'s group; refuse it when in an earlier group\'s.

    A creator another computer holds is judged as that computer\'s session: its id counts only where the cluster or
    the item shows that computer holding it.
    """
    try:
        store = await get_workflow_store(project_root)
    except (OSError, ValueError):
        return ""
    raw = await store.read_state(item)
    if raw is None:
        return ""
    state = TodoState.model_validate(raw)
    holder = state.active_runner or ""
    source = creator_computer if creator_computer and creator_computer != config.computer.name else None
    if holder and await in_claiming_group(initiator_session_id, holder, state.workflow.remote_members, source=source):
        return await register_helper_start(project_root, item, holder, computer)
    if initiator_session_id in await earlier_claim_sessions(state.workflow, holder, item, project_root):
        raise HelperStartRefused(EARLIER_GROUP.format(item=item, session=initiator_session_id))
    return ""
