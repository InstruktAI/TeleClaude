"""Todo/workflow REST endpoints for the telec CLI tool subcommands.

Exposes the next-machine state machine functions (prepare, work)
and roadmap mutation operations (mark-phase, set-deps) as REST endpoints
with dual-factor caller identity enforcement.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException

from teleclaude.api.auth import (
    CLEARANCE_TODOS_INTEGRATE,
    CLEARANCE_TODOS_MARK_PHASE,
    CLEARANCE_TODOS_PREPARE,
    CLEARANCE_TODOS_SET_DEPS,
    CLEARANCE_TODOS_WORK,
    CallerIdentity,
)
from teleclaude.api_models import OperationStatusDTO
from teleclaude.config import config
from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.db import db
from teleclaude.core.integration.state_machine import next_integrate
from teleclaude.core.next_machine import next_prepare
from teleclaude.core.next_machine.core import (
    detect_circular_dependency,
    get_stash_entries,
    has_uncommitted_changes,
    load_roadmap,
    load_roadmap_deps,
    mark_phase,
    save_roadmap,
    sync_main_planning_to_all_worktrees,
)
from teleclaude.core.operations import get_operations_service
from teleclaude.core.operations.service import SerializedOperation

router = APIRouter(prefix="/todos", tags=["todos"])

_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def _default_cwd() -> str:
    return str(config.computer.default_working_dir)


@router.post("/prepare")
async def todo_prepare(  # pyright: ignore
    slug: Annotated[str | None, Body()] = None,
    cwd: Annotated[str | None, Body()] = None,
    hitl: Annotated[bool, Body()] = True,
    identity: CallerIdentity = Depends(CLEARANCE_TODOS_PREPARE),  # noqa: ARG001
) -> dict[str, str]:
    """Run the Phase A (prepare) state machine.

    Checks preparation state for the given slug and returns instructions for
    the next action (draft, gate, or already prepared). Requires clearance to
    invoke the prepare workflow.
    """
    effective_cwd = cwd or _default_cwd()
    result = await next_prepare(db, slug, effective_cwd, hitl)
    return {"result": result}


@router.post("/work", status_code=202, response_model=OperationStatusDTO, response_model_exclude_none=True)
async def todo_work(  # pyright: ignore
    slug: Annotated[str | None, Body()] = None,
    cwd: Annotated[str | None, Body()] = None,
    client_request_id: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(CLEARANCE_TODOS_WORK),
) -> SerializedOperation:
    """Run the Phase B (work) state machine.

    Submits a durable receipt-backed operation for the build/review/fix cycle.
    Uses the caller's session_id for tracking and preserves that identity
    across the async boundary for finalize ownership. Requires clearance to
    invoke the work workflow (typically restricted to orchestrators).
    """
    if not cwd:
        raise HTTPException(status_code=400, detail="cwd required: working directory not provided")
    operations = get_operations_service()
    return await operations.submit_todo_work(
        slug=slug,
        cwd=cwd,
        caller_session_id=identity.session_id,
        client_request_id=client_request_id,
    )


@router.post("/integrate")
async def todo_integrate(  # pyright: ignore
    slug: Annotated[str | None, Body()] = None,
    cwd: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(CLEARANCE_TODOS_INTEGRATE),
) -> dict[str, str]:
    """Run the integration state machine.

    Executes the next deterministic integration step: acquires the lease,
    pops the next candidate from the queue, merges, commits, pushes, and
    cleans up. Returns structured instructions at decision points where
    agent intelligence is required (squash commit composition, conflict
    resolution, push rejection recovery).

    Uses the caller's session_id as the lease owner. Requires integrator
    clearance — workers cannot invoke this directly.
    """
    if not cwd:
        raise HTTPException(status_code=400, detail="cwd required: working directory not provided")
    result = await next_integrate(db, slug, cwd, identity.session_id)
    return {"result": result}


@router.post("/mark-phase")
async def todo_mark_phase(  # pyright: ignore
    slug: Annotated[str, Body()],
    phase: Annotated[str, Body()],
    status: Annotated[str, Body()],
    cwd: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(CLEARANCE_TODOS_MARK_PHASE),  # noqa: ARG001
) -> dict[str, str]:
    """Mark a work phase as complete/approved in state.yaml.

    Updates the phase status for the given slug. Terminal statuses (complete,
    approved) require the worktree to have no uncommitted changes and no stash
    debt. Requires clearance to modify phase state.
    """
    if not cwd:
        raise HTTPException(status_code=400, detail="cwd required: working directory not provided")
    if phase not in ("build", "review"):
        raise HTTPException(status_code=400, detail=f"invalid phase '{phase}': must be 'build' or 'review'")
    valid_statuses = ("pending", "started", "complete", "approved", "changes_requested")
    if status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"invalid status '{status}': must be one of {', '.join(valid_statuses)}",
        )

    worktree_cwd = str(Path(cwd) / WORKTREE_DIR / slug)
    if not Path(worktree_cwd).exists():
        raise HTTPException(status_code=404, detail=f"worktree not found at {worktree_cwd}")

    terminal_statuses = ("complete", "approved")
    if status in terminal_statuses:
        if has_uncommitted_changes(cwd, slug):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"worktree {WORKTREE_DIR}/{slug} has uncommitted changes — commit them before marking phase complete"
                ),
            )
        stash_entries = get_stash_entries(cwd)
        if stash_entries:
            noun = "entry" if len(stash_entries) == 1 else "entries"
            raise HTTPException(
                status_code=409,
                detail=(
                    f"repository has {len(stash_entries)} git stash {noun} — "
                    "clear stash entries before marking phases complete"
                ),
            )

    updated_state = mark_phase(worktree_cwd, slug, phase, status)
    return {"result": f"OK: {slug} state updated - {phase}: {status}", "state": str(updated_state)}


@router.post("/set-deps")
async def todo_set_deps(  # pyright: ignore
    slug: Annotated[str, Body()],
    after: Annotated[list[str], Body()],
    cwd: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(CLEARANCE_TODOS_SET_DEPS),  # noqa: ARG001
) -> dict[str, str]:
    """Set dependencies for a work item in the roadmap.

    Replaces all existing dependencies for the slug with the given list.
    Pass after=[] to clear all dependencies. Validates slugs and checks for
    circular dependencies. Requires clearance to modify roadmap dependencies.
    """
    if not cwd:
        raise HTTPException(status_code=400, detail="cwd required: working directory not provided")

    if not _SLUG_RE.match(slug):
        raise HTTPException(
            status_code=400,
            detail=f"invalid slug '{slug}': must be lowercase alphanumeric with hyphens only",
        )
    for dep in after:
        if not _SLUG_RE.match(dep):
            raise HTTPException(
                status_code=400,
                detail=f"invalid dependency '{dep}': must be lowercase alphanumeric with hyphens only",
            )
    if slug in after:
        raise HTTPException(status_code=400, detail=f"slug '{slug}' cannot depend on itself")

    entries = load_roadmap(cwd)
    if not entries:
        raise HTTPException(status_code=404, detail="todos/roadmap.yaml not found")

    roadmap_slugs = {e.slug for e in entries}
    if slug not in roadmap_slugs:
        raise HTTPException(status_code=404, detail=f"slug '{slug}' not found in roadmap.yaml")
    for dep in after:
        if dep not in roadmap_slugs:
            raise HTTPException(status_code=404, detail=f"dependency '{dep}' not found in roadmap.yaml")

    deps = load_roadmap_deps(cwd)
    cycle = detect_circular_dependency(deps, slug, after)
    if cycle:
        cycle_str = " -> ".join(cycle)
        raise HTTPException(status_code=409, detail=f"circular dependency detected: {cycle_str}")

    for entry in entries:
        if entry.slug == slug:
            entry.after = after
            break

    save_roadmap(cwd, entries)
    sync_main_planning_to_all_worktrees(cwd)

    msg = f"dependencies set for '{slug}': {', '.join(after)}" if after else f"dependencies cleared for '{slug}'"
    return {"result": f"OK: {msg}"}
