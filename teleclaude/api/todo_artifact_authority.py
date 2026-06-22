"""Caller-authority resolution and the role allowlist for todo artifact writes.

The artifact write boundary records *who* wrote (the resolved principal) and, for
prepare artifacts, enforces *who may write* (the prepare-phase role allowlist).
Both concerns live here so the route module stays focused on request routing.
"""

from __future__ import annotations

from fastapi import HTTPException

from teleclaude.api.auth import CallerIdentity
from teleclaude.constants import JobRole
from teleclaude.core.db import db as runtime_db


def resolved_write_principal(identity: CallerIdentity) -> str:
    """Resolve the caller principal recorded as an artifact's ``updated_by``.

    Mirrors ``todo_stamp``: an agent session is recorded under its session id, a
    human-driven terminal under its verified human principal. Caller-supplied
    audit identity is never honored.
    """
    if identity.session_id:
        return identity.session_id
    if identity.principal and identity.principal.startswith("human:"):
        return identity.principal
    if identity.email:
        return f"human:{identity.email}"
    if identity.human_role:
        return "human:terminal"
    raise HTTPException(status_code=403, detail="caller identity required to write artifact")


def optional_capture_principal(identity: CallerIdentity | None) -> str | None:
    """Derive the creator principal for the open create route, non-raising.

    Mirrors ``resolved_write_principal`` but returns ``None`` instead of raising
    when no identity resolves — capture is audit-only and never gates the create.
    For an agent caller the already-resolved principal transparently records the
    chain-root human; for a session-id-authed human it is derived from ``email``.
    """
    if identity is None:
        return None
    if identity.principal:
        return identity.principal
    if identity.email:
        return f"human:{identity.email}"
    return None


async def refuse_non_prepare_writer(identity: CallerIdentity, slug: str, name: str) -> None:
    """Enforce the prepare-artifact caller-role allowlist before any holder check.

    A prepare artifact is writable only by a prepare-phase writer: a direct
    human-identity session (empty session id) or a prepare-orchestrator
    TeleClaude session. Every other persisted job — work orchestrator, create
    orchestrator, integrator, and all worker jobs — is refused by role with a
    403, independent of lifecycle phase and of whether the caller holds the slug.
    """
    if not identity.session_id:
        return
    session = await runtime_db.get_session(identity.session_id)
    job = session.job if session else None
    if job != JobRole.PREPARE_ORCHESTRATOR.value:
        raise HTTPException(
            status_code=403,
            detail=(
                f"prepare artifact '{name}' for '{slug}' is writable only by a "
                f"prepare-orchestrator or human session; caller job '{job or '<none>'}' is refused"
            ),
        )
