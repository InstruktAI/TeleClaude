"""Session visibility rules shared by local and relayed listing surfaces."""

from __future__ import annotations

from collections.abc import Sequence

from teleclaude.caller_identity import (
    CliCaller,
    PersonCliCaller,
    Platform,
    RoleResolver,
    SessionOf,
    SystemCliCaller,
)
from teleclaude.config import config
from teleclaude.constants import HUMAN_ROLE_CUSTOMER
from teleclaude.core.models import SessionSnapshot

_LOCAL_COMPUTER_NAMES = ("", "local")


def sessions_reached_by(
    caller: CliCaller,
    sessions: Sequence[SessionSnapshot],
    *,
    resolver: RoleResolver,
    caller_session: str | None,
) -> list[SessionSnapshot]:
    """Keep sessions whose recorded project lies within the caller's role reach."""
    system_caller = isinstance(caller, SystemCliCaller)
    platform_reaches = system_caller or resolver.role_for(caller, Platform()) != HUMAN_ROLE_CUSTOMER
    reached: list[SessionSnapshot] = []
    for session in sessions:
        local_session = session.computer in (None, *_LOCAL_COMPUTER_NAMES, config.computer.name)
        if not local_session and caller_session and session.initiator_session_id == caller_session:
            reached.append(session)
            continue
        if local_session:
            if system_caller or (
                isinstance(caller, PersonCliCaller)
                and resolver.role_for(caller, SessionOf(session.project_path)) != HUMAN_ROLE_CUSTOMER
            ):
                reached.append(session)
        elif platform_reaches:
            reached.append(session)
    return reached
