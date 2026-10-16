"""The facts about a calling session that the lifecycle acts are judged against.

They are read from the session's record, which the platform wrote when it created the session; the
act command takes nothing about the caller from what the caller typed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from teleclaude.caller_identity import HUMAN_PRINCIPAL_PREFIX
from teleclaude.config.machine import config
from teleclaude.constants import LOCAL_COMPUTER, SYSTEM_DAEMON_PRINCIPAL
from teleclaude.core.db import db
from teleclaude.core.models import SessionSnapshot, parse_peer_session_snapshots
from teleclaude.core.operation_caller_identity import relayed_caller_computer
from teleclaude.core.session_utils import cached_remote_session, session_in_claiming_group
from teleclaude.types.workflow_record import HelperStart, RemoteMember

NO_PRINCIPAL_EMAIL: Final = ""


@dataclass(frozen=True)
class CallerFacts:
    """A session's identity facts: its launch role and job, who started it, and the person it runs for."""

    session_id: str
    role: str | None
    job: str | None
    initiator_session_id: str | None
    principal_email: str

    def is_persons_own_session(self, person_email: str) -> bool:
        """Whether this is a session the person opened themselves, rather than one that carries their lineage.

        All three hold: its principal is the person, no other session started it, and no dispatcher, job or
        procedure activation launched it under a role.
        """
        return (
            bool(person_email)
            and self.principal_email == person_email
            and not self.initiator_session_id
            and not self.role
            and not self.job
        )


async def load_caller(session_id: str) -> CallerFacts | None:
    """Read a session's identity facts from its record; None when the session is unknown."""
    if relayed_caller_computer(session_id) is not None:
        return _remote_caller(session_id)
    session = await db.get_session(session_id)
    if session is None:
        return _remote_caller(session_id)
    principal = session.principal or ""
    email = principal.removeprefix(HUMAN_PRINCIPAL_PREFIX) if principal.startswith(HUMAN_PRINCIPAL_PREFIX) else ""
    return CallerFacts(
        session_id=session_id,
        role=session.role,
        job=session.job,
        initiator_session_id=session.initiator_session_id,
        principal_email=email or NO_PRINCIPAL_EMAIL,
    )


def _remote_caller(session_id: str) -> CallerFacts | None:
    """The facts of a caller that runs on another computer, from the snapshot the mesh delivered for its session.

    The relayed request carries the caller\'s session id; this computer holds no record of that session, so its role,
    job, principal and initiator are read from the cluster cache, the supported source of another computer\'s session
    facts. A session the cache does not know stays unknown.
    """
    snapshot = cached_remote_session(session_id)
    if snapshot is None:
        return None
    principal = snapshot.principal or ""
    email = principal.removeprefix(HUMAN_PRINCIPAL_PREFIX) if principal.startswith(HUMAN_PRINCIPAL_PREFIX) else ""
    return CallerFacts(
        session_id=session_id,
        role=snapshot.role,
        job=snapshot.job,
        initiator_session_id=snapshot.initiator_session_id,
        principal_email=email or NO_PRINCIPAL_EMAIL,
    )


async def anchored_members(holder_session_id: str, recorded: Sequence[RemoteMember]) -> frozenset[str]:
    """The retained remote members that belong to this holder\'s group, and no other holder\'s.

    A retained member belongs to the group only when its parent edge leads back to the holder: the parent is the holder,
    a session that descends from it on this computer, or a member already anchored. A member retained under an earlier
    holder is on that holder\'s edge and so is not in a later holder\'s group, though the item still retains it.
    """
    anchored: set[str] = set()
    changed = True
    while changed:
        changed = False
        for member in recorded:
            if member.session_id in anchored:
                continue
            if member.parent in anchored or await session_in_claiming_group(member.parent, holder_session_id):
                anchored.add(member.session_id)
                changed = True
    return frozenset(anchored)


async def in_claiming_group(
    caller_session_id: str, holder_session_id: str, recorded: Sequence[RemoteMember] = (), *, source: str | None = None
) -> bool:
    """Whether the caller is the holder or a session dispatched, transitively, from it.

    A caller of another computer is a member when the item retains it as one anchored to this holder, and a session of
    this computer is a member when its ancestry reaches the holder directly or through an anchored remote member.
    """
    carried_from = source or relayed_caller_computer(caller_session_id)
    if carried_from is not None:
        return await _relayed_in_claiming_group(caller_session_id, carried_from, holder_session_id, recorded)
    if await session_in_claiming_group(caller_session_id, holder_session_id):
        return True
    anchored = await anchored_members(holder_session_id, recorded)
    if caller_session_id in anchored:
        return True
    for member_id in anchored:
        if await session_in_claiming_group(caller_session_id, member_id):
            return True
    return False


async def _relayed_in_claiming_group(
    caller_session_id: str, source: str, holder_session_id: str, recorded: Sequence[RemoteMember]
) -> bool:
    """Whether a caller another computer carried here is the holder or descends from it.

    A session id is local to the computer that holds it, so the id a computer carries counts only when that same
    computer is positively known to hold such a session: its own snapshot, or a member the item retained from it. An id
    this computer holds itself, or one another computer\'s snapshot carries, is not that caller. Its lineage then
    continues from the initiator its own computer recorded.
    """
    snapshot = cached_remote_session(caller_session_id, source)
    retained = next(
        (member for member in recorded if member.session_id == caller_session_id and member.computer == source), None
    )
    if snapshot is None and retained is None:
        return False
    if caller_session_id == holder_session_id:
        return True
    initiator = snapshot.initiator_session_id if snapshot is not None else retained.parent if retained else None
    return bool(initiator) and await in_claiming_group(str(initiator), holder_session_id, recorded)


async def child_sessions_of(holder_session_id: str) -> tuple[str, ...]:
    """The open sessions the holder started directly."""
    children = await db.list_sessions(all_open=True, initiator_session_id=holder_session_id)
    return tuple(child.session_id for child in children)


@dataclass(frozen=True)
class GroupMember:
    """A live session of a claiming group and the computer it runs on; empty for a session of this computer."""

    session_id: str
    computer: str = ""


@dataclass(frozen=True)
class RemoteView:
    """What this computer knows of the other computers\' open sessions, from the cluster cache."""

    snapshots: tuple[SessionSnapshot, ...] = ()


def _remote_view() -> RemoteView:
    """The cluster cache\'s view of the other computers\' sessions; empty while there is no cache (outside the daemon)."""
    from teleclaude.core.command_registry import get_command_service  # noqa: PLC0415 - deferred cycle

    try:
        cache = get_command_service().client.cache
    except RuntimeError:
        return RemoteView()
    if cache is None:
        return RemoteView()
    others = (LOCAL_COMPUTER, config.computer.name)
    return RemoteView(tuple(s for s in cache.get_sessions() if s.computer not in (None, "", *others)))


# Session ids are never reused, so a session proven closed stays closed; the proof is kept for the process.
_PROVEN_CLOSED: set[str] = set()


async def _open_sessions_of(computer: str) -> tuple[SessionSnapshot, ...] | None:
    """Every open session the named computer holds, read from that computer now; None when it did not answer.

    The answer is the computer\'s own record at the moment it answers. A session it created before this read began is
    in the answer while it is open and absent once it has closed, which is what the cluster cache cannot say: its
    update for a session just created may not have reached this computer yet.
    """
    from teleclaude.core.command_dispatch import (  # noqa: PLC0415 - deferred cycle
        RemoteDispatchError,
        relay_caller_read,
    )
    from teleclaude.core.command_registry import get_command_service  # noqa: PLC0415 - deferred cycle
    from teleclaude.core.relayed_intake import RelayRead  # noqa: PLC0415 - deferred cycle

    try:
        data = await relay_caller_read(
            get_command_service().client, computer, RelayRead.SESSIONS.value, principal=SYSTEM_DAEMON_PRINCIPAL
        )
        listing = [entry for entry in data if isinstance(entry, dict)] if isinstance(data, list) else []
        return tuple(s for s in parse_peer_session_snapshots(listing, computer) if s.closed_at is None)
    except (RemoteDispatchError, RuntimeError, ValueError, OSError):
        return None


def remote_snapshots_present() -> bool:
    """Whether the cluster cache holds any open session of another computer."""
    return bool(_remote_view().snapshots)


@dataclass(frozen=True)
class GroupView:
    """The holder\'s claiming group as far as it is positively known.

    ``unknown`` names the computers that could not be asked about a retained member or a carried creation, and
    ``unresolved`` the retained members whose computer did not answer: neither proven live nor proven ended, so a sweep
    that needs the group settled cannot conclude and an entry that needs an earlier group ended refuses. ``remote`` is
    every remote member seen now, live or not, to be retained.
    """

    live: tuple[GroupMember, ...] = ()
    unknown: tuple[str, ...] = ()
    remote: tuple[RemoteMember, ...] = ()
    unresolved: tuple[str, ...] = ()


async def group_view_of(
    holder_session_id: str, recorded: Sequence[RemoteMember] = (), starts: Sequence[HelperStart] = ()
) -> GroupView:
    """Every session started from the holder, transitively and on any computer, with what is not positively known.

    Sessions of this computer come from its store, through ended intermediates. Sessions of the others come from the
    cluster cache, which holds only the open ones, so the remote members already retained on the item are followed as
    well: a live session started by a remote member that has since ended is still found. A retained member the cache
    does not show open is ended only when its own computer says so: that computer is asked, and its answer, read after
    the member was retained, either lists the member (live) or does not (ended, for good). A computer that does not
    answer leaves its members unresolved. A creation carried to a computer without ever naming its session is found
    the same way, from that computer\'s own listing.
    """
    view = _remote_view()
    open_remote = {snapshot.session_id: snapshot for snapshot in view.snapshots if snapshot.closed_at is None}
    asked = {
        member.computer
        for member in recorded
        if member.session_id not in open_remote and member.session_id not in _PROVEN_CLOSED
    }
    asked |= {start.computer for start in starts if start.computer and not start.session_id}
    fresh: dict[str, tuple[SessionSnapshot, ...] | None] = {
        computer: await _open_sessions_of(computer) for computer in sorted(asked)
    }
    answered = {computer: sessions for computer, sessions in fresh.items() if sessions is not None}
    snapshots = tuple(s for s in view.snapshots if s.computer not in answered) + tuple(
        s for sessions in answered.values() for s in sessions
    )
    open_remote = {snapshot.session_id: snapshot for snapshot in snapshots if snapshot.closed_at is None}
    by_parent: dict[str, list[RemoteMember]] = {}
    for member in recorded:
        by_parent.setdefault(member.parent, []).append(member)
    seen: set[str] = {holder_session_id}
    live: list[GroupMember] = []
    remote: list[RemoteMember] = []
    unknown: set[str] = {computer for computer, sessions in fresh.items() if sessions is None}
    unresolved: list[str] = []
    frontier = [holder_session_id]
    while frontier:
        parent = frontier.pop()
        started = await db.list_sessions(include_closed=True, include_headless=True, initiator_session_id=parent)
        for session in started:
            if session.session_id in seen:
                continue
            seen.add(session.session_id)
            frontier.append(session.session_id)
            if session.closed_at is None:
                live.append(GroupMember(session.session_id))
        for snapshot in snapshots:
            if snapshot.initiator_session_id != parent or snapshot.session_id in seen:
                continue
            seen.add(snapshot.session_id)
            frontier.append(snapshot.session_id)
            remote.append(RemoteMember(session_id=snapshot.session_id, computer=str(snapshot.computer), parent=parent))
            if snapshot.closed_at is None:
                live.append(GroupMember(snapshot.session_id, str(snapshot.computer)))
        for member in by_parent.get(parent, []):
            if member.session_id in seen:
                continue
            seen.add(member.session_id)
            frontier.append(member.session_id)
            remote.append(member)
            if member.session_id in open_remote:
                live.append(GroupMember(member.session_id, member.computer))
            elif member.session_id in _PROVEN_CLOSED or member.computer in answered:
                _PROVEN_CLOSED.add(member.session_id)
            else:
                unresolved.append(member.session_id)
                unknown.add(member.computer)
    return GroupView(tuple(live), tuple(sorted(unknown)), tuple(remote), tuple(unresolved))


async def group_members_of(holder_session_id: str) -> tuple[GroupMember, ...]:
    """Every live session started from the holder, transitively and on any computer; the holder is not among them."""
    return (await group_view_of(holder_session_id)).live


async def group_sessions_of(holder_session_id: str) -> tuple[str, ...]:
    """The ids of every open session started from the holder, transitively and on any computer."""
    return tuple(member.session_id for member in await group_members_of(holder_session_id))
