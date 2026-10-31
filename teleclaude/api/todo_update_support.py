"""Support helpers for the unified todo update route."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException

import teleclaude.core.todo_dependency_warnings as dependency_warnings
from teleclaude.api.auth import CallerIdentity
from teleclaude.api.todo_artifact_authority import refuse_todo_update_outside_claiming_group
from teleclaude.api.todo_dependency_validation import validate_requested_dependencies
from teleclaude.api.work_feedback import DeclaredWorkRefusal
from teleclaude.constants import (
    REMOVED_TODO_MUTATION_REFUSED_DETAIL,
    REMOVED_TODO_RETENTION_WINDOW,
    SLUG_NOT_FOUND_DETAIL,
    TodoStatus,
)
from teleclaude.core.dates import normalize_task_schedule
from teleclaude.core.db import Db
from teleclaude.core.next_machine.dep_graph import detect_circular_dependency
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.next_machine.unclaim import (
    ClaimReleaseRefusal,
    format_claim_release_outcome,
    unclaim_todo_for_caller,
)
from teleclaude.core.todos_db._errors import (
    GroupCycleRefused,
    GroupDependencyConflict,
    HolderReconciliationRefused,
    HolderTransitionRefused,
)
from teleclaude.core.workflow_store.github_store import refuse_if_awaiting_republication
from teleclaude.core.workflow_store.store import WorkflowStore
from teleclaude.types.todo_kind import ALL_DUMP_KINDS
from teleclaude.types.todos import HoldAuditSource

TASK_ERROR_RELEASE_REFUSAL = (
    "is held by a task error and cannot be bare-released. "
    "Recover with `telec todo stamp --task-outcome success` (delivers) "
    "or kill the run and start it manually."
)
_CIRCULAR_DEPENDENCY_DETAIL_TEMPLATE = "circular dependency detected: {cycle}"
_TASK_ERROR_RELEASE_DETAIL_TEMPLATE = "slug '{slug}' {refusal}"
HOLD_REASON_REQUIRED_DETAIL = "reason is required with hold"
HOLD_REASON_REQUIRES_HOLD_DETAIL = "reason is valid only with hold"


def validate_update_request(
    *,
    new_slug: str | None,
    group: str | None,
    after: list[str] | None,
    kind: str | None,
    hold: bool,
    reason: str | None,
    release: bool,
    unclaim: bool,
    schedule: str | None,
) -> str | None:
    if (
        new_slug is None
        and group is None
        and after is None
        and kind is None
        and schedule is None
        and not hold
        and not release
        and not unclaim
    ):
        raise HTTPException(
            status_code=400,
            detail=("at least one of new_slug, group, after, kind, schedule, hold, release, or unclaim is required"),
        )
    if hold and release:
        raise HTTPException(status_code=400, detail="hold and release are mutually exclusive")
    return normalize_hold_reason(hold=hold, reason=reason)


def normalize_hold_reason(*, hold: bool, reason: str | None) -> str | None:
    if reason is not None and not hold:
        raise HTTPException(status_code=400, detail=HOLD_REASON_REQUIRES_HOLD_DETAIL)
    if not hold:
        return None
    if reason is None:
        raise HTTPException(status_code=400, detail=HOLD_REASON_REQUIRED_DETAIL)
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise HTTPException(status_code=400, detail=HOLD_REASON_REQUIRED_DETAIL)
    return normalized_reason


def normalize_schedule_request(schedule: str | None) -> str | None:
    if schedule is None:
        return None
    try:
        return normalize_task_schedule(schedule)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def apply_group_membership_update(
    todos_db: WorkflowStore,
    *,
    slug: str,
    group_slug: str | None,
    requested_after: list[str] | None,
    cwd: str,
    identity: CallerIdentity,
) -> None:
    """Validate and apply the group leg before other update legs can write."""
    if group_slug is not None and not await todos_db.is_structural_group_holder(group_slug):
        await refuse_todo_update_outside_claiming_group(todos_db, identity, group_slug)
    if requested_after is not None:
        await validate_requested_dependencies(todos_db, slug, requested_after, check_membership=False)
        deps = await todos_db.load_deps()
        cycle = detect_circular_dependency(deps, slug, requested_after)
        if cycle:
            cycle_str = " -> ".join(cycle)
            detail = _CIRCULAR_DEPENDENCY_DETAIL_TEMPLATE.format(cycle=cycle_str)
            raise DeclaredWorkRefusal(status_code=409, detail=detail, work_feedback=detail)

    try:
        await todos_db.check_membership_update(
            slug,
            group_slug=group_slug,
            group_present=True,
            after=requested_after,
        )
    except (GroupCycleRefused, GroupDependencyConflict, HolderTransitionRefused) as exc:
        detail = str(exc)
        raise DeclaredWorkRefusal(status_code=409, detail=detail, work_feedback=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        await todos_db.update_membership(
            slug,
            group_slug=group_slug,
            after=requested_after,
            cwd=cwd,
        )
    except (GroupCycleRefused, GroupDependencyConflict, HolderTransitionRefused, HolderReconciliationRefused) as exc:
        detail = str(exc)
        raise DeclaredWorkRefusal(status_code=409, detail=detail, work_feedback=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def apply_dependency_update(
    todos_db: WorkflowStore,
    *,
    slug: str,
    requested_after: list[str] | None,
    group_present: bool,
) -> list[str]:
    """Apply dependencies when not already committed with membership and return warnings."""
    if requested_after is None:
        return []
    if not group_present:
        await validate_requested_dependencies(todos_db, slug, requested_after)
        deps = await todos_db.load_deps()
        cycle = detect_circular_dependency(deps, slug, requested_after)
        if cycle:
            cycle_str = " -> ".join(cycle)
            detail = _CIRCULAR_DEPENDENCY_DETAIL_TEMPLATE.format(cycle=cycle_str)
            raise DeclaredWorkRefusal(status_code=409, detail=detail, work_feedback=detail)
        await todos_db.set_deps(slug, after=requested_after)

    target_status = await todos_db.find_live_slug_conflict(slug)
    if requested_after and target_status == TodoStatus.ACTIVE.value:
        return dependency_warnings.frozen_dep_warnings(slug, await todos_db.get_deps_with_status(slug))
    return []


async def resolve_current_group_slug(todos_db: WorkflowStore, slug: str) -> str | None:
    """Return the live todo's holder slug, or None when it is ungrouped."""
    rows = await todos_db.list_todo(include_icebox=True, include_holders=True)
    slug_by_id = {row["id"]: row["slug"] for row in rows}
    todo = next(
        (row for row in rows if row["slug"] == slug and row["status"] in ("active", "icebox")),
        None,
    )
    return slug_by_id.get(todo["group_id"]) if todo is not None and todo["group_id"] is not None else None


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


async def require_slug_in_todo(todos_db: WorkflowStore, slug: str) -> None:
    """Require a live slug and explain retained removed state when it exists."""
    if await todos_db.slug_in_todo(slug):
        return
    if await todos_db.has_removed_todo(slug):
        detail = REMOVED_TODO_MUTATION_REFUSED_DETAIL.format(
            slug=slug,
            retention_days=REMOVED_TODO_RETENTION_WINDOW.days,
        )
        raise DeclaredWorkRefusal(status_code=404, detail=detail, work_feedback=detail)
    require_slug_found(slug, found=False)


async def apply_hold_update(
    todos_db: WorkflowStore,
    slug: str,
    *,
    hold: bool,
    reason: str | None,
    release: bool,
    caller_session_id: str | None,
) -> bool | None:
    if not hold and not release:
        return None
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        await refuse_if_awaiting_republication(todos_db, slug)
        raise HTTPException(status_code=404, detail=SLUG_NOT_FOUND_DETAIL.format(slug=slug))
    writer = StateWriter(raw_state)
    if release and writer.state.hold_audit.source == HoldAuditSource.TASK_ERROR:
        detail = _TASK_ERROR_RELEASE_DETAIL_TEMPLATE.format(slug=slug, refusal=TASK_ERROR_RELEASE_REFUSAL)
        raise DeclaredWorkRefusal(status_code=409, detail=detail, work_feedback=detail)
    writer.state.hold = hold
    if hold:
        normalized_reason = normalize_hold_reason(hold=hold, reason=reason)
        assert normalized_reason is not None
        writer.state.hold_audit.source = HoldAuditSource.MANUAL
        writer.state.hold_audit.set_at = datetime.now(UTC).isoformat()
        writer.state.hold_audit.set_by_session_id = caller_session_id or ""
        writer.state.hold_audit.reason = normalized_reason
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
    unclaim_outcome = await unclaim_todo_for_caller(
        db,
        slug=slug,
        cwd=cwd,
        caller_session_id=caller_session_id,
    )
    unclaim_summary = format_claim_release_outcome(outcome=unclaim_outcome)
    if isinstance(unclaim_outcome, ClaimReleaseRefusal):
        raise DeclaredWorkRefusal(status_code=409, detail=unclaim_summary, work_feedback=unclaim_summary)
    return unclaim_summary


def should_emit_route_update(
    *,
    group_present: bool,
    kind: str | None,
    requested_after: list[str] | None,
    schedule: str | None,
    hold_value: bool | None,
    unclaim_summary: str | None,
) -> bool:
    return (
        group_present
        or kind is not None
        or requested_after is not None
        or schedule is not None
        or hold_value is not None
        or unclaim_summary is None
    )


__all__ = [
    "apply_dependency_update",
    "apply_group_membership_update",
    "apply_hold_update",
    "apply_unclaim_update",
    "normalize_hold_reason",
    "normalize_schedule_request",
    "require_slug_found",
    "require_slug_in_todo",
    "resolve_current_group_slug",
    "should_emit_route_update",
    "validate_kind_for_update",
    "validate_update_request",
]
