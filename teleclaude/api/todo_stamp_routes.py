"""The unified todo stamp surface.

One daemon-side mutation route for every stamp type — worker verdicts and human
gate approvals alike. Split from ``todo_routes`` so each module stays focused;
both routers mount under the same ``/todos`` prefix.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException

from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.api.todo_routes import _SlugStatusResponse, _validate_slug_for_update
from teleclaude.api.working_copy_request import working_copy_request_deadline
from teleclaude.core.next_machine.code_conformance_return import (
    CodeConformanceReturnRefused,
    return_to_work_for_code_conformance,
)
from teleclaude.core.next_machine.session_hold import notify_runner_of_gate_approval
from teleclaude.core.next_machine.stamps import apply_todo_stamp, is_human_gate_stamp, stamp_follow_through
from teleclaude.core.next_machine.state_mutation import StateMutationError
from teleclaude.git import GitCommandError
from teleclaude.types.todo_return import (
    TodoReturnToWorkApiRoute,
    TodoReturnToWorkRequestField,
    TodoReturnToWorkResultStatus,
)

router = APIRouter(prefix="/todos", tags=["todos"], dependencies=[Depends(working_copy_request_deadline)])
_RETURN_TO_WORK_CWD_REQUIRED = "cwd required: working directory not provided"


def _human_gate_caller_stamp_id(identity: CallerIdentity) -> str:
    if identity.principal and identity.principal.startswith("human:"):
        return identity.principal
    if not identity.session_id and identity.email:
        return f"human:{identity.email}"
    if not identity.session_id and identity.human_role:
        return "human:terminal"
    raise HTTPException(status_code=403, detail="human principal required to approve todo gate")


@router.post(TodoReturnToWorkApiRoute.ROUTER_PATH, response_model=_SlugStatusResponse)
async def todo_return_to_work(
    slug: Annotated[str, Body()],
    reason: Annotated[str, Body()],
    evidence: Annotated[str, Body()],
    cwd: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> _SlugStatusResponse:
    """Return one held, unintegrated finalized candidate to its work cycle."""
    if not cwd:
        raise HTTPException(status_code=400, detail=_RETURN_TO_WORK_CWD_REQUIRED)
    _validate_slug_for_update(slug, field_name=TodoReturnToWorkRequestField.SLUG.value)
    caller_id = identity.session_id or _human_gate_caller_stamp_id(identity)
    try:
        await return_to_work_for_code_conformance(
            cwd=cwd,
            slug=slug,
            reason=reason,
            evidence=evidence,
            caller_session_id=caller_id,
        )
    except CodeConformanceReturnRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (StateMutationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _SlugStatusResponse(status=TodoReturnToWorkResultStatus.OK, slug=slug)


@router.post("/stamp", response_model=_SlugStatusResponse)
async def todo_stamp(
    slug: Annotated[str, Body()],
    stamp_type: Annotated[str, Body()],
    background_tasks: BackgroundTasks,
    cwd: Annotated[str | None, Body()] = None,
    value: Annotated[str, Body()] = "",
    phase: Annotated[str | None, Body()] = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> _SlugStatusResponse:
    """Apply one todo stamp daemon-side, against the initialized session DB.

    The single stamp surface for every stamp type — worker verdicts and human
    gate approvals alike. Caller identity is taken from the verified request
    identity, never the body: a worker session stamps under its session id, a
    human terminal under its human principal. Running here rather than in the
    bare CLI is what gives the authority gate an initialized session DB.

    A stamp's follow-through (a kickback returns the todo to preparation) is
    scheduled on ``background_tasks``, so it runs only after this response is sent.
    """
    if not cwd:
        raise HTTPException(status_code=400, detail="cwd required: working directory not provided")
    _validate_slug_for_update(slug, field_name="slug")
    # ``prd_approved`` is the human-only approval stamp: it records the resolved
    # human principal. Other gates retain their verified session caller for the
    # claim-ownership validation that applies to their existing authority model.
    if stamp_type == "prd_approved":
        caller_id = _human_gate_caller_stamp_id(identity)
    else:
        caller_id = identity.session_id or _human_gate_caller_stamp_id(identity)
    try:
        await apply_todo_stamp(
            cwd=cwd,
            slug=slug,
            stamp_type=stamp_type,
            value=value,
            phase=phase,
            caller_session_id=caller_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (StateMutationError, ValueError, GitCommandError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    follow_through = stamp_follow_through(stamp_type, slug=slug, cwd=cwd, caller_session_id=caller_id)
    if follow_through is not None:
        background_tasks.add_task(follow_through)
    if is_human_gate_stamp(stamp_type):
        await notify_runner_of_gate_approval(cwd, slug, acting_session_id=identity.session_id)
    return _SlugStatusResponse(status="ok", slug=slug)
