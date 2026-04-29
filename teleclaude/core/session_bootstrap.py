"""Session identity bootstrap — atomic tmux + identity file creation."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_bridge
from teleclaude.core.db import db, resolve_session_principal
from teleclaude.core.models import Session
from teleclaude.session_identity import write_session_identity_to

logger = get_logger(__name__)


async def ensure_tmux_with_identity(
    session: Session,
    tmux_name: str,
    working_dir: str,
    env_vars: dict[str, str],
) -> bool:
    """Create tmux session and write full identity file.

    Shared by bootstrap (new sessions), restore (maintenance), and adoption (headless → tmux).
    Returns True on success, False on failure.
    """
    created = await tmux_bridge.ensure_tmux_session(
        name=tmux_name,
        working_dir=working_dir,
        session_id=session.session_id,
        env_vars=env_vars,
    )
    if not created:
        logger.error("Failed to create tmux session for %s", session.session_id)
        return False

    session_tmp = tmux_bridge.get_session_tmpdir(session.session_id)
    if not session_tmp:
        logger.error("No session TMPDIR for %s — cannot write identity", session.session_id)
        return False

    principal, _role = resolve_session_principal(session)
    session_token: str | None = None
    if principal.startswith("system:"):
        session_token = await db.issue_session_token(session.session_id, principal, _role)

    system_role = session.system_role.strip().lower() if session.system_role else None

    write_session_identity_to(
        directory=session_tmp,
        session_id=session.session_id,
        session_token=session_token,
        system_role=system_role,
        human_role=session.human_role,
    )
    return True
