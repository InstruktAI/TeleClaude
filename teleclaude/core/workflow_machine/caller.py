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
from teleclaude.constants import LOCAL_COMPUTER
from teleclaude.core.db import db
from teleclaude.core.models import SessionSnapshot
from teleclaude.core.session_utils import session_in_claiming_group
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
    session = await db.get_session(session_id)
    if session is None:
        return None
    principal = session.principal or ""
    email = principal.removeprefix(HUMAN_PRINCIPAL_PREFIX) if principal.startswith(HUMAN_PRINCIPAL_PREFIX) else ""
    return CallerFacts(
        session_id=session_id,
        role=session.role,
        job=session.job,
        initiator_session_id=session.initiator_session_id,
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
    caller_session_id: str, holder_session_id: str, recorded: Sequence[RemoteMember] = ()
) -> bool:
    """Whether the caller is the holder or a session dispatched, transitively, from it.

    A caller of another computer is a member when the item retains it as one anchored to this holder, and a session of
    this computer is a member when its ancestry reaches the holder directly or through an anchored remote member.
    """
    if await session_in_claiming_group(caller_session_id, holder_session_id):
        return True
    anchored = await anchored_members(holder_session_id, recorded)
    if caller_session_id in anchored:
        return True
    for member_id in anchored:
        if await session_in_claiming_group(caller_session_id, member_id):
            return True
    return False


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
    """What this computer knows of the other computers\' sessions: their open ones, and which computers it has heard from."""

    snapshots: tuple[SessionSnapshot, ...] = ()
    warm: frozenset[str] = frozenset()


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
    snapshots = tuple(s for s in cache.get_sessions() if s.computer not in (None, "", *others))
    return RemoteView(snapshots, cache.computers_heard_from())


def remote_snapshots_present() -> bool:
    """Whether the cluster cache holds any open session of another computer."""
    return bool(_remote_view().snapshots)


@dataclass(frozen=True)
class GroupView:
    """The holder\'s claiming group as far as it is positively known.

    ``unknown`` names the computers a retained remote member runs on and whose sessions this computer has not heard
    since it started: the group there cannot be told from empty, so a sweep that needs the group settled cannot
    conclude. ``remote`` is every remote member seen now, live or not, to be retained.
    """

    live: tuple[GroupMember, ...] = ()
    unknown: tuple[str, ...] = ()
    remote: tuple[RemoteMember, ...] = ()


async def group_view_of(
    holder_session_id: str, recorded: Sequence[RemoteMember] = (), starts: Sequence[HelperStart] = ()
) -> GroupView:
    """Every session started from the holder, transitively and on any computer, with what is not positively known.

    Sessions of this computer come from its store, through ended intermediates. Sessions of the others come from the
    cluster cache, which holds only the open ones, so the remote members already retained on the item are followed as
    well: a live session started by a remote member that has since ended is still found, and a retained member is live
    until the cache shows it closed, or shows its computer heard from without it.
    """
    view = _remote_view()
    by_parent: dict[str, list[RemoteMember]] = {}
    for member in recorded:
        by_parent.setdefault(member.parent, []).append(member)
    open_remote = {snapshot.session_id: snapshot for snapshot in view.snapshots if snapshot.closed_at is None}
    seen: set[str] = {holder_session_id}
    live: list[GroupMember] = []
    remote: list[RemoteMember] = []
    unknown: set[str] = set()
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
        for snapshot in view.snapshots:
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
            elif member.computer not in view.warm:
                unknown.add(member.computer)
    for start in starts:
        if start.computer and not start.session_id and start.computer not in view.warm:
            unknown.add(start.computer)  # a creation carried there that never named its session: unproven empty
    return GroupView(tuple(live), tuple(sorted(unknown)), tuple(remote))


async def group_members_of(holder_session_id: str) -> tuple[GroupMember, ...]:
    """Every live session started from the holder, transitively and on any computer; the holder is not among them."""
    return (await group_view_of(holder_session_id)).live


async def group_sessions_of(holder_session_id: str) -> tuple[str, ...]:
    """The ids of every open session started from the holder, transitively and on any computer."""
    return tuple(member.session_id for member in await group_members_of(holder_session_id))
