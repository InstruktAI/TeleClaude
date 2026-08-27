"""Support helpers for the unified todo update route."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException

from teleclaude.constants import (
    REMOVED_TODO_MUTATION_REFUSED_DETAIL,
    REMOVED_TODO_RETENTION_WINDOW,
    SLUG_NOT_FOUND_DETAIL,
)
from teleclaude.core.dates import normalize_task_schedule
from teleclaude.core.db import Db
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.next_machine.unclaim import unclaim_todo_for_caller
from teleclaude.core.todos_db import TodosDb
from teleclaude.types.todo_kind import ALL_DUMP_KINDS
from teleclaude.types.todos import HoldAuditSource

TASK_ERROR_RELEASE_REFUSAL = (
    "is held by a task error and cannot be bare-released. "
    "Recover with `telec todo stamp --task-outcome success` (delivers) "
    "or kill the run and start it manually."
)


def validate_update_request(
    *,
    new_slug: str | None,
    after: list[str] | None,
    kind: str | None,
    hold: bool,
    release: bool,
    unclaim: bool,
    schedule: str | None,
) -> None:
    if (
        new_slug is None
        and after is None
        and kind is None
        and schedule is None
        and not hold
        and not release
        and not unclaim
    ):
        raise HTTPException(
            status_code=400,
            detail="at least one of new_slug, after, kind, schedule, hold, release, or unclaim is required",
        )
    if hold and release:
        raise HTTPException(status_code=400, detail="hold and release are mutually exclusive")


def normalize_schedule_request(schedule: str | None) -> str | None:
    if schedule is None:
        return None
    try:
        return normalize_task_schedule(schedule)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def validate_kind_for_update(kind: str | None) -> None:
    if kind is not None and kind not in ALL_DUMP_KINDS:
        raise HTTPException(status_code=400, detail=f"unknown todo kind: {kind!r}")


def require_slug_found(slug: str, *, found: bool, detail: str = SLUG_NOT_FOUND_DETAIL) -> None:
    """Raise the canonical not-found error for ``slug`` unless ``found`` is true.

    The single shared shape for turning a not-found condition into the
    canonical error: every caller determines "found" through whatever check
    fits its boundary (an existence probe, a state read, an action's own
    result, a payload-assembly outcome) and passes that boolean here, so the
    exception type and status code never drift between call sites. ``detail``
    is a ``{slug}``-templated string; override it when the failure condition
    is narrower than plain absence (e.g. "not iceboxed" is not "not found").
    """
    if not found:
        raise HTTPException(status_code=404, detail=detail.format(slug=slug))


async def require_slug_in_todo(todos_db: TodosDb, slug: str) -> None:
    """Require a live slug and explain retained removed state when it exists."""
    if await todos_db.slug_in_todo(slug):
        return
    if await todos_db.has_removed_todo(slug):
        raise HTTPException(
            status_code=404,
            detail=REMOVED_TODO_MUTATION_REFUSED_DETAIL.format(
                slug=slug,
                retention_days=REMOVED_TODO_RETENTION_WINDOW.days,
            ),
        )
    require_slug_found(slug, found=False)


async def apply_hold_update(
    todos_db: TodosDb,
    slug: str,
    *,
    hold: bool,
    release: bool,
    caller_session_id: str | None,
) -> bool | None:
    if not hold and not release:
        return None
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        raise HTTPException(status_code=404, detail=SLUG_NOT_FOUND_DETAIL.format(slug=slug))
    writer = StateWriter(raw_state)
    if release and writer.state.hold_audit.source == HoldAuditSource.TASK_ERROR:
        raise HTTPException(status_code=409, detail=f"slug '{slug}' {TASK_ERROR_RELEASE_REFUSAL}")
    writer.state.hold = hold
    if hold:
        writer.state.hold_audit.source = HoldAuditSource.MANUAL
        writer.state.hold_audit.set_at = datetime.now(UTC).isoformat()
        writer.state.hold_audit.set_by_session_id = caller_session_id or ""
        writer.state.hold_audit.reason = "todo update"
    else:
        writer.state.hold_audit.source = HoldAuditSource.NONE
        writer.state.hold_audit.set_at = ""
        writer.state.hold_audit.set_by_session_id = ""
        writer.state.hold_audit.reason = ""
    await writer.commit(todos_db, slug)
    return writer.state.hold


async def apply_unclaim_update(
    db: Db,
    *,
    slug: str,
    cwd: str,
    unclaim: bool,
    caller_session_id: str | None,
) -> str | None:
    if not unclaim:
        return None
    unclaim_summary = await unclaim_todo_for_caller(
        db,
        slug=slug,
        cwd=cwd,
        caller_session_id=caller_session_id,
    )
    if unclaim_summary.startswith("error:"):
        raise HTTPException(status_code=409, detail=unclaim_summary)
    return unclaim_summary


def should_emit_route_update(
    *,
    kind: str | None,
    requested_after: list[str] | None,
    schedule: str | None,
    hold_value: bool | None,
    unclaim_summary: str | None,
) -> bool:
    return (
        kind is not None
        or requested_after is not None
        or schedule is not None
        or hold_value is not None
        or unclaim_summary is None
    )


__all__ = [
    "apply_hold_update",
    "apply_unclaim_update",
    "normalize_schedule_request",
    "require_slug_found",
    "require_slug_in_todo",
    "should_emit_route_update",
    "validate_kind_for_update",
    "validate_update_request",
]
