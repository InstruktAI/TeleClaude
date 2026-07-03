"""Voluntary release of a caller-owned todo claim."""

from __future__ import annotations

from teleclaude.core.db import Db
from teleclaude.core.next_machine.claim_authority import ClaimOwnership, classify_claim_ownership
from teleclaude.core.next_machine.runtime.sessions import is_live_session_id
from teleclaude.core.next_machine.session_hold import _emit_todo_updated
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.todos_db import get_todos_db
from teleclaude.project_root import resolve_state_root


def _refusal(message: str) -> str:
    return f"error: {message}"


def _summary(*, slug: str, cleared_active_runner: bool, cleared_working_slug: bool) -> str:
    cleared: list[str] = []
    if cleared_active_runner:
        cleared.append("active_runner")
    if cleared_working_slug:
        cleared.append("working_slug")
    if not cleared:
        return f"unclaimed {slug}: no owned live claim"
    return f"unclaimed {slug}: cleared {', '.join(cleared)}"


async def unclaim_todo_for_caller(
    db: Db,
    *,
    slug: str,
    cwd: str,
    caller_session_id: str | None,
) -> str:
    project_root = resolve_state_root(cwd)
    todos_db = await get_todos_db(project_root)
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        return _refusal(f"todo {slug!r} was not found")

    session = await db.get_session(caller_session_id) if caller_session_id else None
    caller_working_slug = session.working_slug if session is not None else None
    active_runner = raw_state.get("active_runner")
    claimed_session_id = active_runner if isinstance(active_runner, str) and active_runner else None
    live_claimant = (
        claimed_session_id if claimed_session_id and await is_live_session_id(db, claimed_session_id) else None
    )
    ownership = classify_claim_ownership(
        slug=slug,
        caller_working_slug=caller_working_slug,
        caller_session_id=caller_session_id,
        live_claimant=live_claimant,
    )

    if ownership is ClaimOwnership.CONFLICTING_BINDING:
        return _refusal(
            f"cannot unclaim {slug}: caller session {caller_session_id or '<none>'} "
            f"owns working_slug={caller_working_slug}"
        )
    if ownership is ClaimOwnership.FOREIGN_CLAIM:
        return _refusal(f"cannot unclaim {slug}: live claim is held by session {live_claimant}")

    cleared_active_runner = False
    if ownership is ClaimOwnership.OWNS_CLAIM:
        writer = StateWriter(raw_state)
        writer.state.active_runner = None
        writer.state.manually_started = False
        await writer.commit(todos_db, slug)
        cleared_active_runner = True

    cleared_working_slug = False
    if ownership is ClaimOwnership.OWNS_BINDING and caller_session_id is not None:
        await db.update_session(caller_session_id, working_slug=None)
        cleared_working_slug = True
        if claimed_session_id == caller_session_id:
            writer = StateWriter(raw_state)
            writer.state.active_runner = None
            writer.state.manually_started = False
            await writer.commit(todos_db, slug)
            cleared_active_runner = True

    if cleared_active_runner or cleared_working_slug:
        await _emit_todo_updated(slug=slug, project_path=str(project_root), source="workflow.unclaim")
    return _summary(
        slug=slug,
        cleared_active_runner=cleared_active_runner,
        cleared_working_slug=cleared_working_slug,
    )


__all__ = ["unclaim_todo_for_caller"]
