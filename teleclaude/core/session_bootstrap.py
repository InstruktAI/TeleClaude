"""Session identity bootstrap — atomic tmux + identity file creation."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core import tmux_bridge
from teleclaude.core.db import SessionIdentityError, db, resolve_session_principal
from teleclaude.core.models import Session
from teleclaude.session_identity import rewrite_session_identity_to, write_session_identity_to

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
        principal=principal,
    )
    return True


async def reconcile_session_identity_document(session_id: str) -> bool:
    """Rewrite one live session's identity document from its durable record."""
    session = await db.get_session(session_id)
    if session is None or session.closed_at is not None:
        return False
    session_tmp = tmux_bridge.get_session_tmpdir(session.session_id)
    if not session_tmp:
        return False
    try:
        principal, _role = resolve_session_principal(session)
    except SessionIdentityError:
        return False

    system_role = session.system_role.strip().lower() if session.system_role else None
    rewrite_session_identity_to(
        directory=session_tmp,
        session_id=session.session_id,
        system_role=system_role,
        human_role=session.human_role,
        principal=principal,
    )
    return True


async def reconcile_live_session_identity_documents() -> int:
    """Rewrite identity documents for live sessions on the local computer."""
    sessions = await db.list_sessions(computer_name=config.computer.name, all_open=True)
    reconciled_count = 0
    for session in sessions:
        if await reconcile_session_identity_document(session.session_id):
            reconciled_count += 1
    return reconciled_count
