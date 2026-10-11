"""Resolve current managed callers for one silence observation."""

from __future__ import annotations

from teleclaude.config.machine import config
from teleclaude.core.db import db
from teleclaude.core.session_listeners import SessionListener, get_listeners
from teleclaude.core.session_status import is_session_terminal
from teleclaude.core.tmux_bridge import session_exists


async def resolve_silence_audience(target_session_id: str) -> list[SessionListener]:
    """Resolve persistent caller relationships with a current delivery surface."""
    listeners = await get_listeners(target_session_id)
    eligible: list[SessionListener] = []
    for listener in listeners:
        if listener.one_shot or listener.caller_session_id == target_session_id:
            continue
        caller_computer = listener.caller_computer or config.computer.name
        if caller_computer != config.computer.name:
            eligible.append(listener)
            continue
        caller = await db.get_session(listener.caller_session_id)
        if (
            caller is None
            or is_session_terminal(lifecycle_status=caller.lifecycle_status, closed_at=caller.closed_at)
            or not caller.tmux_session_name
            or not await session_exists(caller.tmux_session_name, log_missing=False)
        ):
            continue
        listener.caller_tmux_session = caller.tmux_session_name
        eligible.append(listener)
    return eligible
