"""Caller-authority resolution and the role allowlist for todo artifact writes.

The artifact write boundary records *who* wrote (the resolved principal) and, for
prepare artifacts, enforces *who may write* (the prepare-phase role allowlist).
Both concerns live here so the route module stays focused on request routing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from fastapi import HTTPException

from teleclaude.api.auth import CallerIdentity
from teleclaude.constants import JobRole
from teleclaude.core.db import db as runtime_db
from teleclaude.core.todos_db._exceptions import ClaimConflict

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb


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
    """Refuse a role-bearing non-prepare writer before any holder check.

    A prepare artifact is writable by a prepare-phase writer — a direct
    human-identity session (empty session id), a registered prepare-orchestrator
    TeleClaude session, or a registered roleless session that carries no job (the
    human-originated, operator-driven shape). The roleless write is then governed
    by the live-holder claim alone. A session id with no registry row is an
    unknown caller and is refused before it can claim; every registered session
    that carries a non-prepare job — work orchestrator, create orchestrator,
    integrator, and all worker jobs — is refused by role with a 403, independent
    of lifecycle phase and of whether the caller holds the slug.
    """
    if not identity.session_id:
        return
    session = await runtime_db.get_session(identity.session_id)
    if session is None:
        raise HTTPException(
            status_code=403,
            detail=(
                f"prepare artifact '{name}' for '{slug}' is not writable by an "
                f"unknown caller; session '{identity.session_id}' is not registered"
            ),
        )
    if session.job is None:
        return
    if session.job != JobRole.PREPARE_ORCHESTRATOR.value:
        raise HTTPException(
            status_code=403,
            detail=(
                f"prepare artifact '{name}' for '{slug}' is not writable by a "
                f"role-bearing session; caller job '{session.job}' is refused"
            ),
        )


async def write_prepare_artifact_claiming(
    todos_db: TodosDb,
    *,
    slug: str,
    name: str,
    content: str,
    updated_by: str | None,
    identity: CallerIdentity,
    resolve_live_holder: Callable[[str | None], Awaitable[str | None]],
) -> None:
    """Write a prepare artifact with claim-on-write and one-session-one-slug reflection.

    Refuses a writer already bound to a different slug (a conflicting session
    binding), performs the atomic claim + write, refuses a live foreign holder,
    then backfills an empty session ``working_slug`` as fallback metadata repair.
    An artifact write carries no lifecycle lane intent, so it never touches the
    session title.
    """
    writer = await runtime_db.get_session(identity.session_id) if identity.session_id else None
    if writer is not None and writer.working_slug and writer.working_slug != slug:
        raise HTTPException(
            status_code=409,
            detail=f"caller session is bound to working_slug={writer.working_slug}; cannot claim '{slug}'",
        )
    holder = await todos_db.write_prepare_artifact_with_claim(
        slug,
        name,
        content,
        updated_by=updated_by,
        claimant_session_id=identity.session_id,
        resolve_live_holder=resolve_live_holder,
    )
    if holder is not None:
        raise HTTPException(status_code=409, detail=ClaimConflict(slug=slug, holder=holder).summary())
    if writer is not None and not writer.working_slug:
        await runtime_db.update_session(identity.session_id, working_slug=slug)
