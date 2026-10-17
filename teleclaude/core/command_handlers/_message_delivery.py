"""Composer-aware dispatch for accepted inbound messages."""

from teleclaude.core import tmux_io
from teleclaude.core.injected_text import InjectedInputAuthority
from teleclaude.core.models import Session
from teleclaude.core.runtime_readiness import RuntimeReadiness
from teleclaude.core.session_status import SessionLifecycleStatus
from teleclaude.core.session_utils import resolve_working_dir


async def inject_inbound_text(
    session: Session,
    text: str,
    *,
    active_agent: str | None,
    authority: InjectedInputAuthority,
    readiness: RuntimeReadiness,
) -> bool | tmux_io.UserTurnDeliveryResult:
    """Preserve inbound composer protection without changing operator paths."""
    working_dir = resolve_working_dir(session.project_path, session.subdir)
    if active_agent and session.lifecycle_status != SessionLifecycleStatus.HEADLESS:
        return await tmux_io.inject_user_turn(
            session,
            text,
            active_agent=active_agent,
            authority=authority,
            readiness=readiness,
        )
    return await tmux_io.route_text(
        session,
        text,
        working_dir=working_dir,
        active_agent=active_agent,
        authority=authority,
        readiness=readiness,
    )
